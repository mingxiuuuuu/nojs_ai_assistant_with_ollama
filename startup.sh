#!/bin/bash

echo "🚀 Starting AI Assistant with Ollama..."

# Load configuration
CONFIG_FILE="config.py"
if [ -f "$CONFIG_FILE" ]; then
    # Extract AVAILABLE_MODELS from config.py
    MODELS_LINE=$(grep -E "AVAILABLE_MODELS.*=.*\[" "$CONFIG_FILE" | head -1)
    if [ ! -z "$MODELS_LINE" ]; then
        # Extract models from the list (basic parsing)
        MODELS_STR=$(echo "$MODELS_LINE" | sed 's/.*\[\(.*\)\].*/\1/' | tr -d '"' | tr ',' ' ')
        read -a models <<< "$MODELS_STR"
        echo "📋 Models from config: ${models[@]}"
    else
        # Fallback models if parsing fails
        models=("mistral" "llama3" "phi3" "tinyllama")
        echo "⚠️  Using fallback models: ${models[@]}"
    fi
else
    # Fallback models if config file not found
    models=("mistral" "llama3" "phi3" "tinyllama")
    echo "⚠️  Config file not found, using fallback models: ${models[@]}"
fi

# Start services in detached mode
echo "📦 Building and starting containers..."
docker-compose up --build -d

# Wait for Ollama to be ready
echo "⏳ Waiting for Ollama service to be ready..."
sleep 15

# Check if Ollama is responding
echo "🔍 Checking Ollama health..."
while ! curl -s http://localhost:11434/api/version > /dev/null; do
    echo "   Waiting for Ollama to respond..."
    sleep 5
done

echo "✅ Ollama is ready!"

# Install models
echo "📥 Installing AI models..."
# models array is now loaded from config.py above

for model in "${models[@]}"; do
    echo "   Pulling $model..."
    docker exec ollama-service ollama pull "$model" || echo "   ⚠️  Failed to pull $model"
done

# Show installed models
echo "📋 Installed models:"
docker exec ollama-service ollama list

# Show status
echo ""
echo "🎉 Setup complete!"
echo "🌐 AI Assistant: http://localhost:8000"
echo "🤖 Ollama API: http://localhost:11434"
echo ""
echo "📊 To check logs:"
echo "   docker-compose logs -f nojs-ai"
echo "   docker-compose logs -f ollama"
echo ""
echo "🛑 To stop services:"
echo "   docker-compose down"