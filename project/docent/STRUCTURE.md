# Docent

Follow the instructions below to install + run the Docent.

## Codebase Structure

[Authored by Claude]

### Frame System (`lib/frames/frames/frame.py`)

The frame system is the core data structure that enables exploration and filtering of data:

1. **FrameFilter Hierarchy**: The base class for all filters that can be applied to data.

   - `FrameFilter`: Abstract base class for all filters
   - `MetadataFilter`: Filters datapoints based on metadata key-value pairs
   - `FramePredicate`: Uses LLM to determine which datapoints satisfy a predicate
   - `ComplexFrameFilter`: Combines multiple filters with logical operations (AND/OR)
   - `ResidualFilter`: Captures datapoints that don't match any other filter
   - `DatapointIdFilter`: Filters by specific datapoint ID

2. **FrameDimension**: Represents a dimension for data exploration with multiple bins (filters).

   - Can be based on either metadata keys or attributes
   - Supports automatic clustering of data using LLMs
   - Manages a set of bins (filters) that partition the data

3. **Frame**: Represents a filtered view of data.

   - Applies a filter to a dataset
   - Computes and caches judgments (whether datapoints match the filter)
   - Provides methods to retrieve matching datapoints

4. **FrameGrid**: The main data structure that ties everything together.
   - Manages multiple dimensions for exploring data
   - Handles operations like marginalization (focusing on specific dimensions)
   - Supports adding/removing dimensions and bins
   - Maintains the state of the exploration session

The system uses asynchronous programming extensively to handle potentially expensive LLM operations without blocking the main thread.

### WebSocket Server (`project/docent/docent/server/main.py`)

The server uses FastAPI to handle WebSocket connections from the frontend:

1. **Connection Management**:

   - `ConnectionManager`: Manages active WebSocket connections
   - `LockManager`: Handles concurrency control for shared resources

2. **Message Handling**:

   - The main WebSocket endpoint (`/ws/framegrid`) dispatches incoming messages to appropriate handlers
   - Messages are processed based on their `action` field
   - Handlers are organized by functionality (session management, dimension updates, interventions, etc.)

3. **Task Dispatching**:

   - Handlers are executed as background tasks using `dispatch_task`
   - This allows long-running operations to proceed without blocking the WebSocket
   - Error handling is centralized in the task dispatcher

4. **Session Management**:
   - FrameGrid sessions are stored in memory and accessed by ID
   - Clients can create or join existing sessions

## Installation

### Backend

The entrypoint to the backend server is in project/docent/docent/server.py. You can run the backend server using project/docent/scripts/api.sh.
The server accepts websocket connections from the frontend client and has a variety of handlers based on the type of request. You can click around the codebase to see what is handled where.

To install + run:
Download artifacts, including models and eval logs:

```bash
luce artifact download mengk && luce artifact download vincent
```

Install the necessary Python packages:

```bash
luce activate && luce install monitor docent
```

Tunnel port 8888 to your local computer:

```bash
# Run this on your local machine
luce tunnel [workstation-name] 8888
```

Run the server:

```bash
luce cd docent && ./scripts/api.sh
```

### Frontend

The frontend repo is located at project/monitor/web. It's a Next.JS 14 (App Router) application deployed on Vercel which uses ShadCN components. You can run an auto-reloading dev server using `project/monitor/scripts/web.sh`.

The main entrypoint to the Docent is at `project/monitor/web/app/dashboard/docent/page.tsx`. You'll see some other code at `[...]/dashboard/chat` which is for our earlier Monitor project; it is not relevant to this project.

The majority of the frontend code was AI-generated via Cursor. Not sure if that makes it harder or easier to work with - let us know :)

To install + run:
We recommend developing the frontend locally, but you can do this from the server too; just `luce tunnel [workstation-name] 3000`.
Install NVM:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
```

Install Node:

```bash
nvm install 22
```

Run the server:

```bash
luce cd monitor && ./scripts/web.sh
```
