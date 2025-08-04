#!/bin/bash

# Deploy to ACR using local Docker build (works on free trial)

echo "🚀 Deploying with ACR (Local Build + Push)..."

# Configuration
RESOURCE_GROUP="nojs-ai-rg-$(date +%m%d%H%M)"
LOCATION="westus2"
UNIQUE=$(date +%m%d%H%M%S)
ACR_NAME="nojsairegistry$UNIQUE"
OLLAMA_CONTAINER="ollama-$UNIQUE"
APP_CONTAINER="nojs-ai-$UNIQUE"
DNS_LABEL="nojs-ai-$UNIQUE"
PROJECT_DIR="."

echo "📋 Configuration:"
echo "   Resource Group: $RESOURCE_GROUP"
echo "   ACR Name: $ACR_NAME"
echo "   Unique ID: $UNIQUE"
echo ""

# Check if Dockerfile exists
if [ ! -f "$PROJECT_DIR/Dockerfile" ]; then
    echo "❌ Dockerfile not found in $PROJECT_DIR"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check Azure login
echo "🔐 Checking Azure login..."
ACCOUNT=$(az account show --query "user.name" --output tsv 2>/dev/null)
if [ -z "$ACCOUNT" ]; then
    echo "❌ Not logged in to Azure. Please run: az login"
    exit 1
fi
echo "✅ Logged in as: $ACCOUNT"

# Create resource group
echo "📦 Creating resource group..."
az group create --name $RESOURCE_GROUP --location $LOCATION --output none
echo "✅ Resource group ready"

# Create Azure Container Registry
echo "🏗️  Creating Azure Container Registry..."
az acr create \
    --resource-group $RESOURCE_GROUP \
    --name $ACR_NAME \
    --sku Basic \
    --admin-enabled true \
    --output none

if [ $? -ne 0 ]; then
    echo "❌ Failed to create Azure Container Registry"
    exit 1
fi
echo "✅ Azure Container Registry created"

# Get ACR login server and credentials
echo "🔑 Getting ACR credentials..."
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query loginServer --output tsv)
ACR_USERNAME=$(az acr credential show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query username --output tsv)
ACR_PASSWORD=$(az acr credential show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query passwords[0].value --output tsv)

echo "✅ ACR Login Server: $ACR_LOGIN_SERVER"

# Build image locally
echo "🔨 Building Docker image locally..."
LOCAL_IMAGE_NAME="nojs-ai-assistant:latest"
ACR_IMAGE_NAME="$ACR_LOGIN_SERVER/nojs-ai-assistant:latest"

docker build -t $LOCAL_IMAGE_NAME $PROJECT_DIR

if [ $? -ne 0 ]; then
    echo "❌ Local Docker build failed"
    exit 1
fi
echo "✅ Image built locally"

# Tag for ACR
echo "🏷️  Tagging image for ACR..."
docker tag $LOCAL_IMAGE_NAME $ACR_IMAGE_NAME
echo "✅ Image tagged: $ACR_IMAGE_NAME"

# Login to ACR
echo "🔐 Logging in to ACR..."
az acr login --name $ACR_NAME

if [ $? -ne 0 ]; then
    echo "❌ Failed to login to ACR"
    exit 1
fi
echo "✅ Logged in to ACR"

# Push to ACR
echo "📤 Pushing image to ACR..."
docker push $ACR_IMAGE_NAME

if [ $? -ne 0 ]; then
    echo "❌ Failed to push to ACR"
    exit 1
fi
echo "✅ Image pushed to ACR"

# Clean up local images to save space
echo "🧹 Cleaning up local images..."
docker rmi $LOCAL_IMAGE_NAME $ACR_IMAGE_NAME 2>/dev/null || true

# Deploy Ollama
echo "🦙 Deploying Ollama..."
az container create \
    --resource-group $RESOURCE_GROUP \
    --name $OLLAMA_CONTAINER \
    --image ollama/ollama:latest \
    --os-type Linux \
    --cpu 2 \
    --memory 7 \
    --ports 11434 \
    --ip-address Public \
    --environment-variables OLLAMA_HOST=0.0.0.0 OLLAMA_ORIGINS="*" \
    --restart-policy Always \
    --output none

echo "✅ Ollama deployed, waiting for it to be ready..."
sleep 30

# Get Ollama IP and test connectivity
OLLAMA_IP=$(az container show --resource-group $RESOURCE_GROUP --name $OLLAMA_CONTAINER --query ipAddress.ip --output tsv)
echo "   Ollama IP: $OLLAMA_IP"

# Wait for Ollama to be responsive with proper health checks
echo "🔍 Testing Ollama connectivity..."
RETRY_COUNT=0
MAX_RETRIES=12
OLLAMA_READY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ] && [ "$OLLAMA_READY" = "false" ]; do
    if curl -s --connect-timeout 5 "http://$OLLAMA_IP:11434/api/version" > /dev/null 2>&1; then
        OLLAMA_READY=true
        echo "✅ Ollama is responding and ready"
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   Attempt $RETRY_COUNT/$MAX_RETRIES: Ollama not ready, waiting 15 seconds..."
        sleep 15
    fi
done

if [ "$OLLAMA_READY" = "false" ]; then
    echo "❌ Ollama failed to become ready after $((MAX_RETRIES * 15)) seconds"
    echo "   Check Ollama logs: az container logs --resource-group $RESOURCE_GROUP --name $OLLAMA_CONTAINER"
    echo "   You can continue deployment, but the app might not work immediately"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Deploy your app using ACR image
echo "🎯 Deploying your app from ACR..."
az container create \
    --resource-group $RESOURCE_GROUP \
    --name $APP_CONTAINER \
    --image $ACR_LOGIN_SERVER/nojs-ai-assistant:latest \
    --registry-login-server $ACR_LOGIN_SERVER \
    --registry-username $ACR_USERNAME \
    --registry-password $ACR_PASSWORD \
    --os-type Linux \
    --cpu 1 \
    --memory 2 \
    --ports 8000 \
    --ip-address Public \
    --dns-name-label $DNS_LABEL \
    --environment-variables ENVIRONMENT=production DEBUG=true HOST=0.0.0.0 PORT=8000 OLLAMA_URL=http://$OLLAMA_IP:11434 DB_PATH=/app/data/chat.db \
    --restart-policy Always \
    --output none

echo "✅ App deployed, waiting 15 seconds..."
sleep 15

# Get public URL
PUBLIC_URL=$(az container show --resource-group $RESOURCE_GROUP --name $APP_CONTAINER --query ipAddress.fqdn --output tsv)

# Install models
echo "📥 Installing AI models..."
MODELS=("mistral" "llama3" "phi3" "tinyllama")

for MODEL in "${MODELS[@]}"; do
    echo "📦 Installing $MODEL..."
    az container exec \
        --resource-group $RESOURCE_GROUP \
        --name $OLLAMA_CONTAINER \
        --exec-command "ollama pull $MODEL" \
        --output none
    echo "✅ $MODEL installed"
done

# Final result
echo ""
echo "🎉 DEPLOYMENT COMPLETE using Azure Container Registry!"
echo "===================================================="
echo "🔗 URL: http://$PUBLIC_URL:8000"
echo "🏗️  ACR: $ACR_LOGIN_SERVER"
echo ""
echo "💡 What happened:"
echo "   ✅ Built Docker image locally (bypasses ACR Tasks limitation)"
echo "   ✅ Pushed to your private Azure Container Registry"
echo "   ✅ Deployed to Azure Container Instances"
echo "   ✅ Installed AI models"
echo ""
echo "🔧 To delete everything later:"
echo "   az group delete --name $RESOURCE_GROUP --yes"