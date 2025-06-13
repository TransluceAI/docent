## Refactor Collaboration Rules

When collaborating on a refactor, follow these guidelines for effective, high-quality, and low-risk changes:

1. **Incremental Refactoring**
   - Start with a direct copy of the old logic/UI, then incrementally refactor and modernize. This allows for easy comparison and ensures you don't lose subtle behaviors or edge cases.

2. **Side-by-Side Comparison**
   - When possible, render both the old and new components simultaneously to visually compare and ensure feature parity.

3. **Copy HTML Structure for Pixel-Perfect Refactors**
   - If the goal is to match an existing UI, copy the HTML/JSX structure and classnames first, then refactor logic/state as needed. This avoids "drift" and ensures the new component is a drop-in replacement.

4. **Move State Down When Possible**
   - If state is only used by a subcomponent, move it into that component. This reduces prop drilling, makes the parent cleaner, and improves reusability.

5. **Type Safety and Redux Thunks**
   - When using Redux thunks, always use the correct `AppDispatch` type for `dispatch` to avoid linter/type errors. Check the actual types of data in the backend and types files to avoid subtle bugs.

6. **Match All Interactions, Not Just Visuals**
   - Ensure that all behaviors (e.g., disabling buttons, auto-resetting forms, clearing filters) are matched, not just the look. Test edge cases (e.g., boolean fields, number parsing, empty state).

7. **Use the Codebase as the Source of Truth**
   - When in doubt, check the backend/data model for how data is expected to be structured. Don't guess at types or formats—look them up.

8. **Flag and Discuss Potential Improvements**
   - If you see a potential tech debt improvement, cleanup, or architectural enhancement (e.g., pushing state downward, extracting reusable logic), flag it and ask the user if they want to address it as part of the refactor. Decide together before proceeding. 