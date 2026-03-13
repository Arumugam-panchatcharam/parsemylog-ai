# AI Chat Assistant

## Overview

AI Chat Assistant provides LLM-powered natural language querying of logs and analysis results.

## Key Capabilities

- **Natural Language Queries** - Ask questions in plain English
- **Context-Aware** - Access to project logs, telemetry, patterns
- **Multi-Turn Conversations** - Maintains chat history
- **File Retrieval** - Automatically fetches relevant log sections
- **LLM Integration** - OpenAI, Anthropic, local models

## Usage

### Start Conversation

```
┌──────────────────────────────────────────────────────┐
│ AI Chat - CPE: AABBCCDDEEFF                          │
│ [New Conversation] [History ▼]                       │
├──────────────────────────────────────────────────────┤
│ You: Show me all WiFi disconnects in the last hour  │
│                                                      │
│ AI: I found 12 WiFi disconnect events between       │
│ 17:30 and 18:30. Here's a summary:                  │
│                                                      │
│ 1. 17:32:10 - Disconnected from MyNetwork (reason=4)│
│ 2. 17:45:23 - Disconnected from MyNetwork (reason=3)│
│ ...                                                  │
│                                                      │
│ The most common disconnect reason is 4 (disassoc    │
│ due to inactivity). Would you like me to show the   │
│ context around these events?                         │
│                                                      │
│ Type your message...                                 │
│ ┌────────────────────────────────────────────────┐   │
│ │                                                │   │
│ └────────────────────────────────────────────────┘   │
│ [Send]                                               │
└──────────────────────────────────────────────────────┘
```

### Example Queries

```
"What caused the reboot at 14:32:10?"
"Compare CPU usage before and after the last reboot"
"Find all errors related to DHCP"
"Summarize telemetry trends for the past week"
"What's the correlation between signal strength and disconnects?"
```

## API Reference

```http
POST /api/<project_id>/chat/send
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cpe_id": "AABBCCDDEEFF",
  "conversation_id": 42,
  "message": "Show me all WiFi disconnects in the last hour"
}

Response:
{
  "message_id": 123,
  "response": "I found 12 WiFi disconnect events...",
  "context_files": ["merged_logs.txt:12345-12356"],
  "suggested_actions": ["View in Log Viewer", "Generate Report"]
}
```

## Configuration

### LLM Settings

```
┌──────────────────────────────────────────────────────┐
│ LLM Configuration                                    │
│ Provider: [OpenAI ▼]                                 │
│ Model: [gpt-4o ▼]                                    │
│ API Key: [sk-...────────────]                        │
│ Temperature: [0.3────] (0.0 = deterministic)         │
│ Max Tokens: [2000───]                                │
│ [Test Connection] [Save]                             │
└──────────────────────────────────────────────────────┘
```

## Related Features

- [Semantic Search](./SEMANTIC_SEARCH.md)
- [Log Viewer](./LOG_VIEWER.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)
