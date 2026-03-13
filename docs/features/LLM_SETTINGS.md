# LLM Settings

## Overview

LLM Settings allows admins to configure external LLM providers for AI features like chat assistant and semantic analysis.

## Supported Providers

- **OpenAI** - GPT-4o, GPT-4-turbo, GPT-3.5-turbo
- **Anthropic** - Claude 3 Opus, Sonnet, Haiku
- **Azure OpenAI** - GPT-4 deployments
- **Local Models** - via API endpoint

## Usage

### Configure Provider

```
┌──────────────────────────────────────────────────────┐
│ LLM Configuration                                    │
│ Provider: [OpenAI ▼]                                 │
│ Model: [gpt-4o ▼]                                    │
│ API Key: [sk-...────────────] [Show]                 │
│ API Endpoint: [https://api.openai.com/v1───]         │
│                                                      │
│ Model Parameters:                                    │
│ Temperature: [0.3────] (0.0-2.0)                     │
│ Max Tokens: [2000───]                                │
│                                                      │
│ [Test Connection] [Save]                             │
└──────────────────────────────────────────────────────┘

✅ Connection successful!
Model: gpt-4o
Latency: 234ms
```

### Test Query

```
Test Query:
"Summarize the key features of this log analysis platform."

Response:
This log analysis platform provides:
1. Semantic search using vector embeddings
2. Drain3 template extraction
3. Multi-CPE fleet management
4. Telemetry visualization
5. Pattern governance with NATCO system

Response time: 1.2s
Tokens used: 145
```

## API Reference

```http
GET /api/admin/settings/llm
Authorization: Bearer <access_token>

Response:
{
  "provider": "openai",
  "model": "gpt-4o",
  "api_endpoint": "https://api.openai.com/v1",
  "temperature": 0.3,
  "max_tokens": 2000,
  "configured": true
}

PUT /api/admin/settings/llm
Content-Type: application/json
{
  "provider": "openai",
  "model": "gpt-4o",
  "api_key": "sk-...",
  "temperature": 0.3,
  "max_tokens": 2000
}
```

## Best Practices

- **API Key Security:** Never expose in client-side code
- **Cost Monitoring:** Set token limits to control costs
- **Model Selection:** Use GPT-4o for quality, GPT-3.5-turbo for speed
- **Temperature:** 0.0-0.3 for deterministic, 0.7-1.0 for creative

## Related Features

- [AI Chat Assistant](./AI_CHAT.md)
- [Semantic Search](./SEMANTIC_SEARCH.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)
