---
name: frontend-build-guard
description: Validates frontend build after code changes, catches TypeScript errors, import issues, linting violations, and missing dependencies. Automatically fixes common errors and rebuilds. Use when editing React components, TypeScript files, or when the user mentions frontend changes, build errors, or type errors.
---

# Frontend Build Guard

Automatically validate frontend builds after code changes and fix common build errors.

## When to Apply

Apply this skill **automatically** after:
- Editing `.tsx`, `.ts`, `.jsx`, `.js` files in `frontend/src/`
- Modifying React components or hooks
- Changing type definitions or interfaces
- Adding new imports or dependencies

Apply **on request** for:
- Config file changes (`vite.config.ts`, `tsconfig.json`, `package.json`)
- Build troubleshooting
- Pre-deployment validation

## Build Validation Workflow

### Step 1: Quick Type Check

Run TypeScript compiler to catch type errors:

```bash
cd frontend && npx tsc --noEmit
```

**Common TypeScript errors and fixes:**

| Error Pattern | Fix |
|---------------|-----|
| `Cannot find module 'X'` | Check import path, ensure module is installed |
| `Property 'X' does not exist` | Add property to interface or use optional chaining |
| `Type 'X' is not assignable to type 'Y'` | Check type compatibility, add type assertion if safe |
| `Argument of type 'X' is not assignable` | Fix function call argument types |

### Step 2: Full Build

Run the complete build process (TypeScript + Vite):

```bash
cd frontend && npm run build
```

This runs: `tsc -b && vite build`

### Step 3: Lint Check (if errors persist)

```bash
cd frontend && npm run lint
```

## Auto-Fix Strategy

When build errors are found, attempt fixes in this order:

### 1. Missing Dependencies

```bash
# Install missing package
cd frontend && npm install <package-name>
```

**Detection patterns:**
- `Cannot find module '@mui/icons-material/XIcon'` → Install `@mui/icons-material`
- `Module not found: Can't resolve 'X'` → Install `X`

### 2. Import Path Errors

**Common issues:**
- Wrong file extension (`.ts` vs `.tsx`)
- Missing `@/` alias resolution
- Incorrect relative path depth

**Fix approach:**
1. Check if file exists with different extension
2. Verify path aliases in `vite.config.ts` and `tsconfig.json`
3. Count `../` correctly from current file to target

### 3. Type Errors

**Pattern: Property doesn't exist**
```typescript
// Error: Property 'newProp' does not exist on type 'Props'
// Fix: Add to interface
interface Props {
  existingProp: string;
  newProp: string;  // Add this
}
```

**Pattern: Null/undefined access**
```typescript
// Error: Object is possibly 'undefined'
// Fix: Use optional chaining or null check
const value = data?.field ?? defaultValue;
```

**Pattern: Type mismatch**
```typescript
// Error: Type 'string' is not assignable to type 'number'
// Fix: Convert type or fix source
const count = parseInt(stringValue, 10);
```

### 4. Linting Issues

Common auto-fixable ESLint errors:
- Unused imports → Remove import
- Missing semicolons → Add semicolons
- Inconsistent quotes → Normalize to project style
- `console.log` statements → Remove or comment

## Error Resolution Process

Follow this decision tree:

```
Build error found
    │
    ├─ Missing dependency?
    │   └─ Install package → Rebuild
    │
    ├─ Import path wrong?
    │   └─ Fix path → Rebuild
    │
    ├─ Type error?
    │   ├─ Simple fix (optional chaining, type assertion)?
    │   │   └─ Apply fix → Rebuild
    │   └─ Complex type issue?
    │       └─ Report error with context and suggestions
    │
    └─ Lint error?
        ├─ Auto-fixable?
        │   └─ Run `npm run lint -- --fix` → Rebuild
        └─ Manual fix needed?
            └─ Report specific violations
```

## Validation Commands Reference

```bash
# Type check only (fast)
cd frontend && npx tsc --noEmit

# Full build (slower, catches more issues)
cd frontend && npm run build

# Lint check
cd frontend && npm run lint

# Lint with auto-fix
cd frontend && npm run lint -- --fix

# Clean build (if cache issues suspected)
cd frontend && rm -rf dist node_modules/.vite && npm run build
```

## Success Criteria

Build is valid when:
- ✅ `tsc --noEmit` exits with code 0
- ✅ `npm run build` completes without errors
- ✅ `npm run lint` reports no errors (warnings OK)
- ✅ `frontend/dist/` directory created with assets

## Common Error Patterns

### React 19 Specific

```typescript
// Error: forwardRef is deprecated in React 19
// Old:
const Component = forwardRef((props, ref) => { ... });

// New:
const Component = (props) => {
  // ref is now a regular prop
  const { ref, ...rest } = props;
  ...
};
```

### Material UI v7

```typescript
// Error: Import not found
// Old: import { Button } from '@mui/material';
// Check if component moved in v7 docs
```

### Vite Build Issues

```typescript
// Error: Could not resolve entry module
// Fix: Check vite.config.ts entry points match actual files
```

## Reporting Format

When reporting errors that need manual intervention:

```markdown
## Build Validation Failed ❌

**Error Type:** [TypeScript | Import | Lint | Dependency]
**File:** `frontend/src/path/to/file.tsx:42`

**Error Message:**
```
[Exact error message from compiler]
```

**Suggested Fix:**
[Specific fix recommendation]

**Context:**
[Relevant code snippet showing the error location]
```

## Post-Fix Verification

After applying fixes:

1. Run `tsc --noEmit` again to verify type errors cleared
2. Run `npm run build` to ensure full build succeeds
3. If build succeeds, report:
   ```
   ✅ Build validated successfully
   - TypeScript: No errors
   - Vite build: Completed
   - Output: frontend/dist/
   ```

## Edge Cases

**Circular dependencies:**
- TypeScript may report confusing errors
- Check import graph for cycles
- Refactor to break circular imports

**Cache corruption:**
- Manifest as random, inconsistent errors
- Fix: Delete `node_modules/.vite` and rebuild

**Version mismatches:**
- React 19 with old @types/react
- Check package.json dependencies align

## Integration with Development Workflow

This skill complements (doesn't replace):
- IDE real-time type checking
- Git pre-commit hooks
- CI/CD pipeline checks

**Key difference:** This skill provides immediate feedback and auto-fixes during interactive coding sessions.
