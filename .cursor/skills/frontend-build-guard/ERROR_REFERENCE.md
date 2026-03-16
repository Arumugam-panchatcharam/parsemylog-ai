# Frontend Build Error Reference

Comprehensive guide to common build errors and their solutions.

## TypeScript Errors

### Module Resolution

#### Error: Cannot find module '@/components/...'

**Cause:** Path alias not configured or misconfigured

**Check:**
```typescript
// vite.config.ts
resolve: {
  alias: {
    '@': '/src',  // Ensure this exists
  },
}

// tsconfig.json
"paths": {
  "@/*": ["./src/*"]  // Ensure this exists
}
```

**Fix:** Ensure both configs have matching alias definitions.

---

#### Error: Module '"X"' has no exported member 'Y'

**Causes:**
1. Named export doesn't exist
2. Using named import for default export
3. TypeScript definitions out of sync with package

**Fix:**
```typescript
// Wrong
import { Button } from '@mui/material/Button';

// Right
import Button from '@mui/material/Button';
// OR
import { Button } from '@mui/material';
```

---

### Type Compatibility

#### Error: Type 'string | undefined' is not assignable to type 'string'

**Fix options:**

```typescript
// Option 1: Optional chaining with fallback
const value = data?.field ?? 'default';

// Option 2: Type guard
if (data?.field) {
  const value: string = data.field;
}

// Option 3: Non-null assertion (use carefully)
const value = data!.field;

// Option 4: Update type to accept undefined
interface Props {
  field: string | undefined;
}
```

---

#### Error: Argument of type 'X' is not assignable to parameter of type 'Y'

**Common scenarios:**

```typescript
// Scenario 1: Event handler types
// Wrong
const handleClick = (e: Event) => { ... };

// Right (React synthetic event)
const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => { ... };

// Scenario 2: Array methods
// Wrong
const ids = items.map(item => item.id); // string[]
doSomething(ids); // expects number[]

// Right
const ids = items.map(item => parseInt(item.id, 10));
```

---

### React 19 Specific

#### Error: 'forwardRef' is deprecated

**Migration:**

```typescript
// Old (React 18)
import { forwardRef } from 'react';

const MyComponent = forwardRef<HTMLDivElement, Props>((props, ref) => {
  return <div ref={ref}>{props.children}</div>;
});

// New (React 19)
interface Props {
  children: React.ReactNode;
  ref?: React.Ref<HTMLDivElement>;
}

const MyComponent = ({ children, ref }: Props) => {
  return <div ref={ref}>{children}</div>;
};
```

---

## Vite Build Errors

### Asset Loading

#### Error: Failed to resolve import "./assets/image.png"

**Cause:** Asset path incorrect or file doesn't exist

**Fix:**
```typescript
// Relative path from component file
import logo from './assets/logo.png';

// OR use public folder (no import needed)
// Place in: frontend/public/logo.png
// Reference as: <img src="/logo.png" />
```

---

### Dynamic Imports

#### Error: Failed to load module script: Expected a JavaScript module

**Cause:** Trying to dynamically import non-existent chunk

**Fix:**
```typescript
// Ensure the imported module exists
const Component = lazy(() => import('./Component')); // ✓
const Missing = lazy(() => import('./DoesNotExist')); // ✗

// For conditionally loaded modules, check existence first
```

---

## ESLint Errors

### React Hooks

#### Error: React Hook "X" is called conditionally

**Rule:** Hooks must be called at the top level

```typescript
// Wrong
if (condition) {
  const [state, setState] = useState(0);
}

// Right
const [state, setState] = useState(0);
if (condition) {
  // Use state here
}
```

---

#### Error: React Hook useEffect has missing dependencies

**Fix:**
```typescript
// Add all dependencies
useEffect(() => {
  fetchData(id, name);
}, [id, name]); // Include all variables used

// OR wrap in useCallback if dependency is a function
const fetchData = useCallback(() => { ... }, []);
useEffect(() => {
  fetchData();
}, [fetchData]);

// OR disable if intentional (with comment explaining why)
useEffect(() => {
  // Only run on mount
  init();
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []);
```

---

### Unused Variables

#### Error: 'X' is defined but never used

**Auto-fix:**
```bash
cd frontend && npm run lint -- --fix
```

**Manual alternatives:**
```typescript
// Remove the variable
// OR prefix with underscore if needed for destructuring
const { used, _unused } = props;

// OR use it
console.log(X);
```

---

## Dependency Errors

### Missing Peer Dependencies

#### Error: npm WARN ... requires a peer of X but none is installed

**Fix:**
```bash
cd frontend && npm install X@version
```

**Common cases:**
- `@types/react` for React libraries
- `@types/node` for Node.js APIs

---

### Version Conflicts

#### Error: Could not resolve dependency: peer X@"Y" from Z

**Cause:** Package requires specific version range

**Fix options:**

```bash
# Option 1: Install compatible version
npm install X@Y

# Option 2: Update package.json
# Edit package.json, change version
npm install

# Option 3: Force install (last resort)
npm install --legacy-peer-deps
```

---

## Build Optimization Issues

### Large Bundle Size

**Warning:** (!) Some chunks are larger than 500 KiB

**Solutions:**

```typescript
// 1. Code splitting with lazy loading
const HeavyComponent = lazy(() => import('./HeavyComponent'));

// 2. Tree-shaking - use named imports
import { Button } from '@mui/material'; // ✓ Only Button
import * as Mui from '@mui/material'; // ✗ Everything

// 3. Check vite.config.ts for manual chunks
build: {
  rollupOptions: {
    output: {
      manualChunks: {
        'vendor-mui': ['@mui/material', '@mui/icons-material'],
        'vendor-plotly': ['plotly.js-dist-min', 'react-plotly.js'],
      },
    },
  },
},
```

---

## Quick Diagnostic Commands

```bash
# See which files have TypeScript errors
npx tsc --noEmit | grep "error TS"

# Count total errors
npx tsc --noEmit 2>&1 | grep -c "error TS"

# Find files with specific error code
npx tsc --noEmit 2>&1 | grep "TS2307"  # Cannot find module

# Check bundle size
npm run build && du -sh frontend/dist/assets/*.js

# Analyze bundle composition
npx vite-bundle-visualizer
```
