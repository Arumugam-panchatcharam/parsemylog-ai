# ParseMyLog-AI Documentation

Welcome to the comprehensive documentation for ParseMyLog-AI - an enterprise-grade log analysis platform with semantic search, machine learning anomaly detection, and multi-CPE support.

## 📚 Documentation Structure

```
docs/
├── README.md                    # This file - documentation index
├── ARCHITECTURE.md              # System design and data flow
├── FEATURES.md                  # Complete feature catalog
├── QUICK_START.md               # Setup and development guide
├── API_REFERENCE.md             # REST API documentation (TODO)
├── DEPLOYMENT.md                # Production deployment (TODO)
├── TROUBLESHOOTING.md           # Common issues (TODO)
├── USER_GUIDE.md                # End-user documentation (existing)
├── KNOWLEDGE_GRAPH_USER_GUIDE.md    # Knowledge graph feature (existing)
├── BATCH_JOBS_LOCAL_TESTING.md      # Batch job testing (existing)
└── features/                    # Detailed feature documentation
    ├── README.md                # Feature docs index
    ├── FILE_UPLOAD.md           # ✅ Complete
    ├── SEMANTIC_SEARCH.md       # ✅ Complete
    ├── MULTI_CPE.md             # ✅ Complete
    └── [21 more features...]    # 📝 TODO
```

## 🚀 Quick Links

### For New Users
- **[Quick Start Guide](./QUICK_START.md)** - Get up and running in 5 minutes
- **[User Guide](./USER_GUIDE.md)** - End-user walkthrough of all features

### For Developers
- **[Architecture Guide](./ARCHITECTURE.md)** - Understand the system design
- **[Features Overview](./FEATURES.md)** - Browse all available features
- **[API Reference](./API_REFERENCE.md)** - REST API documentation (TODO)
- **[Feature Documentation](./features/)** - Detailed guides for each feature

### For Administrators
- **[Deployment Guide](./DEPLOYMENT.md)** - Production setup (TODO)
- **[Troubleshooting](./TROUBLESHOOTING.md)** - Common issues (TODO)

## 📖 Core Documentation

### [Architecture Guide](./ARCHITECTURE.md)
Comprehensive system architecture documentation covering:
- System overview and component interactions
- Data storage layers (SQLite, Qdrant, Redis, File Storage)
- Data flow pipelines (upload, search, telemetry, batch processing)
- Security architecture and authentication
- Scalability considerations
- Monitoring and observability

**When to read:** Before contributing code or deploying to production

### [Features Overview](./FEATURES.md)
Complete catalog of all features with:
- 21 detailed feature descriptions
- Links to individual feature guides
- Feature comparison matrix
- Roadmap for upcoming features

**When to read:** To understand what the platform can do

### [Quick Start Guide](./QUICK_START.md)
Step-by-step setup instructions for:
- Production deployment with Docker Compose
- Local development environment setup
- First-time configuration
- Common development tasks
- Troubleshooting setup issues

**When to read:** First time setting up the project

## 🎯 Feature Documentation

### Completed Guides

| Feature | Description | Link |
|---------|-------------|------|
| **File Upload & Extraction** | Tarball upload with CPE detection | [FILE_UPLOAD.md](./features/FILE_UPLOAD.md) |
| **Semantic Search** | Vector-based log search with BGE embeddings | [SEMANTIC_SEARCH.md](./features/SEMANTIC_SEARCH.md) |
| **Multi-CPE Support** | Isolated processing of multiple devices | [MULTI_CPE.md](./features/MULTI_CPE.md) |

### In Progress

The following features have basic documentation in [FEATURES.md](./FEATURES.md) but need detailed guides:

**High Priority:**
- Log Viewer
- Drain3 Pattern Analysis
- NATCO Governance
- Telemetry Dashboard
- Pattern Analyzer

**Medium Priority:**
- CPE Overview Dashboard
- ML Anomaly Detection
- Batch Processing
- AI Chat Assistant

**Lower Priority:**
- Knowledge Graph (has [separate guide](./KNOWLEDGE_GRAPH_USER_GUIDE.md))
- PCAP Analysis
- Issue Analysis
- User Management
- NATCO Administration

See [features/README.md](./features/README.md) for the complete list and contribution guidelines.

## 🔧 Technical References

### Technology Stack

**Frontend:**
- React 19 + TypeScript
- Vite for build tooling
- Material UI v7 + Tailwind CSS v4
- Plotly.js for visualizations
- TanStack Query for state management

**Backend:**
- Flask 3.1 + Gunicorn
- Celery 5.4 for async tasks
- SQLAlchemy 2.0 ORM
- PyTorch 2.8 + SentenceTransformers

**Data Stores:**
- Qdrant (vector database)
- SQLite/PostgreSQL (relational data)
- Redis (message broker)
- PyArrow Parquet (caching)

**Infrastructure:**
- Docker Compose
- Nginx (reverse proxy)
- Linux/macOS/Windows (WSL2)

### Key Concepts

**Drain3 Templates:**
Log parsing algorithm that extracts patterns from unstructured logs by replacing variable parts with wildcards.

Example:
```
Input:  [wifi] ERROR: Failed to connect to SSID MyNetwork (code: 12)
Output: [wifi] ERROR: Failed to connect to SSID <*> (code: <*>)
```

**BGE Embeddings:**
Dense vector representations (384 dimensions) of log templates for semantic similarity search using BAAI/bge-small-en-v1.5 model.

**CPE (Customer Premises Equipment):**
Individual devices (gateways, modems, routers) identified by MAC address or serial number.

**NATCO (National Company):**
Deployment region or country-specific configuration set used for pattern governance.

**Vector Collection:**
Qdrant database collection storing embeddings for a specific project + CPE combination.

## 📋 API Quick Reference

### Authentication

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}

Response:
{
  "access_token": "eyJ0eXAiOiJKV1...",
  "refresh_token": "eyJ0eXAiOiJKV1...",
  "user": {...}
}
```

### Projects

```http
GET /api/projects
Authorization: Bearer <access_token>

POST /api/projects
{
  "name": "My Project",
  "natco_id": 1  // optional
}
```

### File Upload

```http
POST /api/<project_id>/files/upload
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

Body: file=<tarball>
```

### Semantic Search

```http
POST /api/<project_id>/ai-analysis/search?cpe_id=<cpe_id>
{
  "query": "WiFi connection failures",
  "top_k": 10
}
```

**Full API Reference:** [API_REFERENCE.md](./API_REFERENCE.md) (TODO)

## 🐛 Troubleshooting

### Common Issues

**Docker services won't start:**
```bash
# Check logs
docker compose logs -f

# Verify Docker is running
docker info

# Restart services
docker compose down && docker compose up -d --build
```

**Port conflicts:**
```bash
# Change APP_PORT in .env
echo "APP_PORT=40902" >> .env
docker compose up -d
```

**Frontend build fails:**
```bash
# Increase Node memory
docker compose --profile build run --rm \
  -e NODE_OPTIONS="--max-old-space-size=4096" \
  frontend-build
```

**More:** See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) (TODO)

## 🤝 Contributing

### Documentation Contributions

We welcome documentation improvements! To contribute:

1. **Fork the repository**
2. **Create a branch:** `git checkout -b docs/your-improvement`
3. **Make your changes:**
   - Add new feature docs in `docs/features/`
   - Update existing docs for accuracy
   - Fix typos or improve clarity
4. **Follow the style guide:**
   - Use clear, concise language
   - Include code examples
   - Add cross-references
   - Test all code snippets
5. **Submit a pull request**

**Documentation Style Guide:**
- Use Markdown formatting
- Include code blocks with language tags
- Add visual aids (tables, diagrams)
- Link to related documentation
- Keep line length <120 characters

### Needed Documentation

**High Priority:**
- API Reference (complete REST API docs)
- Deployment Guide (production best practices)
- Performance Tuning Guide
- Detailed feature guides (18 remaining)

**Medium Priority:**
- Troubleshooting Guide (expand common issues)
- Configuration Reference
- Security Best Practices
- Migration Guides (upgrades)

**Community Docs:**
- Video tutorials
- Blog posts / case studies
- Integration examples
- FAQ

## 📝 Documentation Standards

### File Organization

```
docs/
├── Core docs (ARCHITECTURE, FEATURES, etc.)
├── features/
│   ├── README.md (index)
│   └── Individual feature guides
└── assets/ (images, diagrams - TODO)
```

### Naming Conventions

- Use UPPERCASE for core docs: `ARCHITECTURE.md`
- Use UPPERCASE for feature docs: `FILE_UPLOAD.md`
- Use descriptive names: `QUICK_START.md` not `SETUP.md`
- Use underscores for multi-word: `SEMANTIC_SEARCH.md`

### Content Structure

Every feature doc should include:

1. **Overview** - What it does, key capabilities
2. **How It Works** - Technical details, architecture
3. **Usage** - Examples, step-by-step guides
4. **API Reference** - Endpoints, parameters, responses
5. **Troubleshooting** - Common issues, solutions
6. **Related Features** - Cross-references

### Markdown Style

**Headers:**
```markdown
# H1 - Document Title
## H2 - Major Sections
### H3 - Subsections
```

**Code Blocks:**
````markdown
```language
code here
```
````

**Links:**
```markdown
[Text](./relative/path.md)
[External](https://example.com)
```

**Tables:**
```markdown
| Header 1 | Header 2 |
|----------|----------|
| Data 1   | Data 2   |
```

## 🔗 External Resources

### Related Projects

- **[Drain3](https://github.com/logpai/Drain3)** - Log template mining
- **[Qdrant](https://qdrant.tech/documentation/)** - Vector database
- **[BGE Embeddings](https://huggingface.co/BAAI/bge-small-en-v1.5)** - Sentence embeddings
- **[ripgrep](https://github.com/BurntSushi/ripgrep)** - Fast text search

### Learning Resources

- **React:** https://react.dev/learn
- **Flask:** https://flask.palletsprojects.com/
- **Docker:** https://docs.docker.com/get-started/
- **TypeScript:** https://www.typescriptlang.org/docs/

## 📧 Support

- **GitHub Issues:** https://github.com/your-org/parsemylog-ai/issues
- **Discussions:** https://github.com/your-org/parsemylog-ai/discussions
- **Email:** support@your-domain.com

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.

---

**Last Updated:** 2024-03-13  
**Version:** 1.0.0  
**Maintainers:** ParseMyLog-AI Team
