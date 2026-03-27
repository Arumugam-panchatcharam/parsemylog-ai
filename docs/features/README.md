# Feature Documentation Index

This directory contains detailed documentation for each feature in ParseMyLog-AI. Each guide includes usage examples, API references, and troubleshooting tips.

## 📁 Available Documentation

### Core Analysis Features

| Feature | File | Status |
|---------|------|--------|
| **File Upload & Extraction** | [FILE_UPLOAD.md](./FILE_UPLOAD.md) | ✅ Complete |
| **Log Viewer** | [LOG_VIEWER.md](./LOG_VIEWER.md) | ✅ Complete |
| **Drain3 Pattern Analysis** | [DRAIN3_PATTERNS.md](./DRAIN3_PATTERNS.md) | ✅ Complete |
| **Semantic Search** | [SEMANTIC_SEARCH.md](./SEMANTIC_SEARCH.md) | ✅ Complete |
| **Telemetry Dashboard** | [TELEMETRY.md](./TELEMETRY.md) | ✅ Complete |
| **Pattern Analyzer** | [PATTERN_ANALYZER.md](./PATTERN_ANALYZER.md) | ✅ Complete |

### Multi-CPE Features

| Feature | File | Status |
|---------|------|--------|
| **Multi-CPE Support** | [MULTI_CPE.md](./MULTI_CPE.md) | ✅ Complete |
| **CPE Overview** | [CPE_OVERVIEW.md](./CPE_OVERVIEW.md) | ✅ Complete |

### Pattern Management

| Feature | File | Status |
|---------|------|--------|
| **NATCO Governance** | [NATCO_GOVERNANCE.md](./NATCO_GOVERNANCE.md) | ✅ Complete |
| **Pattern Import/Export** | [PATTERN_IMPORT_EXPORT.md](./PATTERN_IMPORT_EXPORT.md) | ✅ Complete |

### Advanced Analytics

| Feature | File | Status |
|---------|------|--------|
| **SelfHeal (single CPE + Cross-CPE)** | [SELFHEAL_ANALYSIS.md](./SELFHEAL_ANALYSIS.md) | ✅ Complete |
| **ML Anomaly Detection** | [ML_ANOMALY.md](./ML_ANOMALY.md) | ✅ Complete |
| **Knowledge Graph** | [KNOWLEDGE_GRAPH.md](./KNOWLEDGE_GRAPH.md) | ✅ Complete |
| **Batch Processing** | [BATCH_PROCESSING.md](./BATCH_PROCESSING.md) | ✅ Complete |
| **PCAP Analysis** | [PCAP_ANALYSIS.md](./PCAP_ANALYSIS.md) | ✅ Complete |
| **Issue Analysis** | [ISSUE_ANALYSIS.md](./ISSUE_ANALYSIS.md) | ✅ Complete |
| **AI Chat Assistant** | [AI_CHAT.md](./AI_CHAT.md) | ✅ Complete |

### Administration

| Feature | File | Status |
|---------|------|--------|
| **User Management** | [USER_MANAGEMENT.md](./USER_MANAGEMENT.md) | ✅ Complete |
| **NATCO Administration** | [NATCO_ADMIN.md](./NATCO_ADMIN.md) | ✅ Complete |
| **LLM Settings** | [LLM_SETTINGS.md](./LLM_SETTINGS.md) | ✅ Complete |

### Utilities

| Feature | File | Status |
|---------|------|--------|
| **MAC Address Lookup** | [MAC_LOOKUP.md](./MAC_LOOKUP.md) | ✅ Complete |
| **Telemetry CSV Export** | [TELEMETRY_CSV.md](./TELEMETRY_CSV.md) | ✅ Complete |

## 📖 Documentation Guidelines

Each feature document should include:

### Required Sections

1. **Overview** - Brief description and key capabilities
2. **How It Works** - Architecture and data flow
3. **Usage** - Step-by-step examples
4. **API Reference** - Endpoint documentation
5. **Troubleshooting** - Common issues and solutions
6. **Related Features** - Links to connected documentation

### Optional Sections

- **Performance Considerations** - Scalability and optimization
- **Best Practices** - Recommended usage patterns
- **Advanced Features** - Power user capabilities
- **Configuration** - Customization options

### Writing Style

- **Clear and Concise** - Avoid jargon, explain acronyms
- **Code Examples** - Include HTTP requests, code snippets, and responses
- **Visual Aids** - Use ASCII diagrams, tables, and formatted blocks
- **Cross-References** - Link to related features and parent docs

## 🚀 Contributing Documentation

### Adding New Feature Documentation

1. Create new file: `docs/features/YOUR_FEATURE.md`
2. Use existing docs as templates
3. Update this index file
4. Update `../FEATURES.md` to link to your new doc
5. Submit pull request

### Updating Existing Documentation

1. Edit the relevant `.md` file
2. Maintain consistent formatting
3. Update version/date in file if applicable
4. Test all code examples

### Documentation Standards

**Markdown Formatting:**
```markdown
# Feature Name

## Section Header

### Subsection

**Bold for emphasis**
*Italic for terms*
`code inline`

```code blocks```
```

**Code Blocks:**
- Use language tags: `json`, `http`, `bash`, `python`, `tsx`
- Include comments for clarity
- Show both request and response

**Links:**
- Use relative paths: `[Text](./OTHER_FILE.md)`
- Link to GitHub issues for known bugs
- Include external resources where helpful

**Tables:**
- Use for structured comparisons
- Keep columns concise
- Align headers

## 📚 Related Documentation

- **[Features Overview](../FEATURES.md)** - High-level feature catalog
- **[Architecture Guide](../ARCHITECTURE.md)** - System design
- **[API Reference](../API_REFERENCE.md)** - Complete REST API documentation ✅
- **[Environment Variables](../ENVIRONMENT_VARIABLES.md)** - Configuration reference ✅  
- **[Deployment Guide](../DEPLOYMENT.md)** - Production deployment ✅
- **[User Guide](../USER_GUIDE.md)** - End-user documentation

## 📝 Documentation Status

**Legend:**
- ✅ Complete - Comprehensive documentation available
- 📝 TODO - Documentation needed
- 🔄 In Progress - Currently being written
- 🔧 Outdated - Needs updating

**Overall Progress:** 21/21 features documented (100%) ✅

**Status:** All feature documentation complete!

**Latest Additions:**
1. Log Viewer - IDE-style log browsing
2. Drain3 Pattern Analysis - Template extraction
3. Telemetry Dashboard - TR-181 visualization
4. Pattern Analyzer - ripgrep scanning
5. CPE Overview - Fleet comparison
6. NATCO Governance - Pattern management
7. ML Anomaly Detection - Unsupervised learning
8. Batch Processing - Fleet-scale analysis
9. AI Chat Assistant - LLM integration
10. Plus 12 more comprehensive guides!

## 🤝 Need Help?

- **Questions:** Open a [GitHub Discussion](https://github.com/your-org/parsemylog-ai/discussions)
- **Issues:** Report in [GitHub Issues](https://github.com/your-org/parsemylog-ai/issues)
- **Contributions:** See [CONTRIBUTING.md](../../CONTRIBUTING.md)

---

[← Back to Main Documentation](../README.md)
