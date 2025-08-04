# NoJS AI Assistant - Azure Cloud Deployment Guide

A comprehensive guide for deploying your NoJS AI Assistant to Azure Container Instances with Ollama backend.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Deployment Process](#deployment-process)
- [Performance Optimization](#performance-optimization)

## Prerequisites

### Required Software
- **Docker Desktop** - Running and accessible 
- **Azure CLI** - Latest version installed
- **Git Bash or Terminal** - For running scripts
- **Azure Account** - Free trial or paid subscription

### Verify Prerequisites
```bash
# Check Docker is running
docker --version
docker info

# Check Azure CLI
az --version

# Check if you can run bash scripts
bash --version
```

## Initial Setup

### 1. Azure Login and Verification

```bash
# Login to Azure
az login

# Verify your account
az account show

# List available subscriptions (if you have multiple)
az account list --output table

# Set specific subscription if needed
az account set --subscription "Your-Subscription-Name"
```

## Deployment Process 

### 1. Git clone repository and start deployment

```bash
git clone https://github.com/mingxiuuuuu/nojs_ai_assistant_with_ollama.git
cd nojs_ai_assistant_with_ollama
```
### 2. Make Deployment Script Executable

```bash
chmod +x deploy-acr-aci.sh
```

### 3. Run Deployment

```bash
./deploy-acr-aci.sh
```

### 3. What the Script Does

The deployment script performs these steps automatically:

#### **Phase 1: Infrastructure Setup**
1. **Creates unique resource group** - Avoids naming conflicts
2. **Creates Azure Container Registry (ACR)** - Private Docker registry
3. **Enables ACR admin access** - For container authentication

#### **Phase 2: Image Preparation**
1. **Builds Docker image locally** - Uses your Dockerfile
2. **Tags image for ACR** - Prepares for private registry
3. **Pushes to ACR** - Uploads to Azure private registry
4. **Cleans up local images** - Saves disk space
**Note**:  az acr build is part of ACR Tasks, which is only supported on Standard-tier ACR. Therefore, free azure account does not have access to az acr build to build docker image and push into the Azure Container Registry directly. In this case, you need to build the image locally and push it to ACR manually.

#### **Phase 3: Ollama Deployment**
1. **Deploys Ollama container** with:
   - 2 CPU cores, 7GB RAM
   - Public IP address (crucial for connectivity)
   - Proper environment variables
2. **Waits for Ollama to start** - Up to 3 minutes
3. **Tests Ollama connectivity** - Health checks
4. **Installs AI models** - Downloads tinyllama, phi3:mini, qwen2:0.5b

#### **Phase 4: App Deployment**
1. **Deploys your app container** with:
   - 1 CPU core, 2GB RAM
   - Public IP and DNS name
   - Correct Ollama URL configuration
2. **Links app to Ollama** - Sets proper environment variables

#### **Phase 5: Final Configuration**
1. **Provides access URLs** - Your app's public address
2. **Shows management commands** - For monitoring and cleanup

### 4. Expected Output

```
🚀 Deploying with ACR (Local Build + Push)...
📋 Configuration:
   Resource Group: nojs-ai-rg-08041145
   ACR Name: nojsairegistry08041145
   Unique ID: 0804114523

🔐 Checking Azure login...
✅ Logged in as: your-email@example.com

📦 Creating resource group...
✅ Resource group ready

🏗️  Creating Azure Container Registry...
✅ Azure Container Registry created

🔨 Building Docker image locally...
✅ Image built locally

📤 Pushing image to ACR...
✅ Image pushed to ACR

🦙 Deploying Ollama...
✅ Ollama deployed, waiting for it to be ready...
   Ollama IP: 4.157.123.45
✅ Ollama is responding and ready

🎯 Deploying your app from ACR...
✅ App deployed, waiting 15 seconds...

📥 Installing AI models...
✅ tinyllama installed
✅ mistral installed
✅ llama3 installed
✅ phi3 installed

🎉 DEPLOYMENT COMPLETE using Azure Container Registry!
====================================================
🔗 URL: http://nojs-ai-0804124244.westus2.azurecontainer.io:8000
🏗️  ACR: nojsairegistry0804124244.azurecr.io
```
## Performance Optimization

### Slow Response Times (15-40 seconds)

This is **normal** for self-hosted Ollama on Azure Container Instances due to:
- CPU-only inference (no GPU)
- Limited compute resources
- Virtualization overhead
- Large model sizes

### For Production-Grade Performance (Faster latency)
1. Use of hosted AI APIs such as OpenAI API, Groq API etc (recommended) 
2. Azure Virtual Machine with GPU (self hosted)

### Performance Comparison

| Solution | Response Time | Cost/Month | Setup Complexity |
|----------|---------------|------------|------------------|
| **Self-hosted Ollama (ACI)** | 15-40s | $10-20 | Medium |
| **OpenAI API** | 1-3s | $20-50 | Low |
| **Groq API** | 1-3s | $0-10 | Low |
| **Azure OpenAI** | 1-4s | $15-40 | Medium |
| **VM with GPU** | 2-5s | $100-200 | High |

