# Docent Development Guidelines

## Python

If you are Codex, make sure you are running Python with the local `.venv/bin/python` interpreter. Furthermore, any Python-related modules you run must also be in that `bin` folder.
If you are Claude, your commands are run from the correct directory by default, so DO NOT prefix commands with `.venv/bin`.

### Type Checking with `pyright`

Configuration is in `pyproject.toml`. Use `pyright` for Python type checking:

```bash
pyright
```

To speed up type checking or focus on specific areas, target specific files or directories:

```bash
pyright path/to/file.py
pyright path/to/directory/
```

### Linting and Formatting with `ruff`

Configuration is in `pyproject.toml` under `[tool.ruff]`. Use `ruff` for linting and formatting:

```bash
ruff format
```

### Sessions and Services

Application services should accept a DB session and required services. This way, transaction management is handled across services.

```python
class Service:
    def __init__(self, session: AsyncSession, ...services):
        self.session = session
        ...
```

In cases where services need to immediately commit results (e.g., computing searches), you can pass an additional writer_session_ctx factory:

```python
class DiffService:
    def __init__(
        self,
        session: AsyncSession,
        writer_session_ctx: Callable[[], AsyncContextManager[AsyncSession]],
        ...services,
    ):
        self.session = session
        self.writer_session_ctx = writer_session_ctx
        ...
```

Other notes:
- Flushing and committing are the responsibility of the service *callers* (e.g., workers, HTTP handlers), not the service itself, except in rare cases.
- Methods in services should accept SQLAlchemy model instances as input, *not* IDs. The caller is responsible for pulling the instance from the database and validating its existence. When used together with dependency injection, this also reduces calls to the database.
- In services, make sure to distinguish variables pointing to SQLAlchemy model instances from Pydantic objects. Prefix variables pointing to SQLAlchemy model instances with `sq_`.

### SQLAlchemy Schema Rules

#### Type Hints

Always use `Mapped[T]` for type hints. This helps pyright understand the type of the column and raise type errors.

#### Foreign Keys and Cascade Deletes

Use database-level cascade deletes via the `ondelete` parameter in `ForeignKey` constraints instead of SQLAlchemy `relationship()` cascades:

```python
parent_id = mapped_column(
    String(36),
    ForeignKey(f"{TABLE_PARENT}.id", ondelete="CASCADE"),
    nullable=False,
    index=True
)
```

This ensures cascading happens at the database level, which is more reliable and performant than ORM-level cascades.

#### Column Specifications

Always explicitly specify nullable behavior:

```python
summary: Mapped[str] = mapped_column(Text, nullable=False)
focus: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Use appropriate column types:
- `String(36)` for UUIDs
- `Text` for long text content
- `JSONB` for complex data structures
- `Boolean` for true/false values

Always add indexes to foreign key columns:

```python
collection_id: Mapped[str] = mapped_column(
    String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
)
```

#### Pydantic Integration

Every SQLAlchemy model must implement both conversion methods:

```python
@classmethod
def from_pydantic(cls, model: PydanticModel, additional_params: str) -> "SQLAModel":
    """Convert Pydantic model to SQLAlchemy model"""
    return cls(
        id=model.id,
        # ... other fields
    )

def to_pydantic(self) -> PydanticModel:
    """Convert SQLAlchemy model to Pydantic model"""
    return PydanticModel(
        id=self.id,
        # ... other fields
    )
```

When converting models with relationships, handle nested objects properly:

```python
@classmethod
def from_pydantic(cls, diff_result: DiffResult, query_id: str) -> "SQLADiffResult":
    sqla_instances = (
        [
            SQLADiffInstance.from_pydantic(instance, diff_result.id)
            for instance in diff_result.instances
        ]
        if diff_result.instances is not None
        else []
    )
    return cls(
        id=diff_result.id,
        instances=sqla_instances,
        # ... other fields
    )
```

## TypeScript (docent_core/_web/)

### Linting with ESLint

Configuration is in `docent_core/_web/.eslintrc.json`. From the `docent_core/_web/` directory:

```bash
# Check for issues
npm run lint

# Auto-fix issues
npm run lint-fix
```

### State Management

- Use Redux slices in `app/store` to store frontend state
- Use RTK queries in `app/api` to access the backend through APIs.
    - We're still migrating API calls from thunks to RTK queries. Do not change any existing thunks unless the user explicitly tells you to do a refactor. However, any new functionality should be implemented using the RTK pattern.

### Styling

#### Spacing

- **Prefer `space-y-*` over individual margins**: When vertically stacking elements, use Tailwind's `space-y-*` utility on the parent container instead of adding `mt-*` or `mb-*` margins to each child element.

  ```tsx
  // Good
  <div className="space-y-4">
    <Component />
    <Component />
    <Component />
  </div>

  // Avoid
  <div>
    <Component className="mb-4" />
    <Component className="mb-4" />
    <Component />
  </div>
  ```

- Similarly, use `space-x-*` for horizontal spacing instead of `ml-*` or `mr-*` on children.

- This keeps spacing logic centralized in the parent, making it easier to adjust and maintain consistent gaps.

- **Default spacing convention**: Containers should use `p-3` for outer padding, with `space-y-3` between groups of elements inside.

  ```tsx
  <div className="p-3 space-y-3">
    <GroupA />
    <GroupB />
    <GroupC />
  </div>
  ```

- **Keep spacing values consistent within components**: Use the same spacing scale for outer padding and inner gaps. If a component uses `p-3` for padding, prefer `space-y-3` or `gap-3` for internal spacing rather than mixing different values like `p-2` with `gap-4`.

  ```tsx
  // Good - consistent spacing
  <div className="p-3 space-y-3">
    <div>...</div>
    <div>...</div>
  </div>

  // Avoid - jarring inconsistency, especially in small components
  <div className="p-2 space-y-4">
    <div>...</div>
    <div>...</div>
  </div>
  ```

  This is especially important for smaller components where mismatched spacing creates visual imbalance. Larger containers have more flexibility to vary spacing based on content hierarchy.

#### Color System

**Base Layout Colors:**
- `bg-background` - Main page/app background
- `bg-secondary` - Secondary surfaces, sidebars, toolbars, panels
- `border-border` - Standard borders and dividers

**Text Colors:**
- `text-primary` - Headings, emphasis, important text
- `text-muted-foreground` - Subheadings, captions, softer text
- Prefer `text-muted-foreground` against `bg-background`, `text-primary` against colored surfaces

**Semantic Colors (use instead of generic destructive/success classes):**
- **Blue**: `bg-blue-bg`, `border-blue-border`, `text-blue-text`, `bg-blue-muted` (hover states)
- **Indigo**: `bg-indigo-bg`, `border-indigo-border`, `text-indigo-text`, `bg-indigo-muted` (search results, highlights)
- **Green**: `bg-green-bg`, `border-green-border`, `text-green-text`, `bg-green-muted` (success, play buttons)
- **Red**: `bg-red-bg`, `border-red-border`, `text-red-text`, `bg-red-muted` (errors, delete actions)
- **Orange**: `bg-orange-bg`, `border-orange-border`, `text-orange-text` (warnings)
- **Yellow**: `bg-yellow-bg`, `border-yellow-border`, `text-yellow-text`, `bg-yellow-muted`
- **Purple**: `bg-purple-bg`, `border-purple-border`, `text-purple-text`

**Border Usage:**
- Default borders use `--border` variable automatically
- For contrasting borders, use `border-primary/20` or semantic colors
- Focus rings: rarely used, `ring-ring` available if needed

**Hover States:**
- Use `-muted` variants for subtle hover effects
- For bright hover states, use low opacity `-text` variants (e.g., `hover:bg-red-text/10`)

**Color System Rules:**
1. **Never use arbitrary color values** - always use the defined color system
2. **Use semantic colors over generic ones** - `text-red-text` not `text-destructive`
3. **Maintain contrast** - `text-primary` on colored backgrounds, `text-muted-foreground` on neutral backgrounds
4. **Follow the naming convention** - `bg-[color]-bg`, `border-[color]-border`, `text-[color]-text`
5. **Check both light and dark modes** - all colors are defined for both themes in `globals.css`

### React Patterns

- **Avoid `useEffect` when possible**: `useEffect` is often overused. Prefer these alternatives:

  - **Derived/computed values**: If something can be calculated from props or state, compute it during render instead of syncing it with an effect.

    ```tsx
    // Good - derive during render
    const fullName = `${firstName} ${lastName}`;

    // Avoid - unnecessary effect
    const [fullName, setFullName] = useState('');
    useEffect(() => {
      setFullName(`${firstName} ${lastName}`);
    }, [firstName, lastName]);
    ```

  - **Event handlers**: If something should happen in response to a user action, put it in the event handler, not an effect.

    ```tsx
    // Good - handle in event
    const handleSubmit = () => {
      saveData();
      showToast('Saved!');
    };

    // Avoid - effect reacting to state change
    useEffect(() => {
      if (submitted) showToast('Saved!');
    }, [submitted]);
    ```

  - **`useMemo`**: For expensive calculations that depend on props/state.

  - **`key` prop**: To reset component state when an ID changes, use `key={id}` instead of an effect that resets state.

  - **Refs**: For DOM interactions like focus, scroll, or measurements, use ref callbacks instead of effects.

    ```tsx
    // Good - ref callback
    <input ref={(el) => el?.focus()} />

    // Avoid - effect for DOM interaction
    const inputRef = useRef(null);
    useEffect(() => {
      inputRef.current?.focus();
    }, []);
    ```
