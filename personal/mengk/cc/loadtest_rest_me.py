#%%
# IPython autoreload setup
try:
    from IPython import get_ipython

    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

#%%
# Configuration
import time

BASE_URL = "https://api.docent-bridgewater.transluce.org"
COOKIE_KEY = "docent_session"

# Load test parameters
NUM_CONCURRENT = 250  # concurrent dashboard page loads per wave
NUM_WAVES = 5  # number of waves to send
DELAY_BETWEEN_WAVES = 0.5  # seconds between waves
COUNTS_BATCH_SIZE = 20  # matches frontend BATCH_SIZE

#%%
# Step 1: Create a session by logging in (or creating an anonymous session)
import httpx

LOGIN_EMAIL = "kevin.meng@bwater.com"
LOGIN_PASSWORD = "1234"


async def get_session_cookie() -> str:
    """Try login first, fall back to anonymous session."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post(
            "/rest/login",
            json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        )
        if resp.status_code == 200:
            session_id = resp.json().get("session_id")
            if session_id:
                print(f"Logged in as {LOGIN_EMAIL}, session_id={session_id[:12]}...")
                return session_id
            cookie = resp.cookies.get(COOKIE_KEY)
            if cookie:
                print(f"Logged in as {LOGIN_EMAIL}, got session from cookie")
                return cookie

        print(f"Login failed ({resp.status_code}), falling back to anonymous session...")

        resp = await client.post("/rest/anonymous_session")
        if resp.status_code == 200:
            session_id = resp.json().get("session_id")
            if session_id:
                print(f"Created anonymous session: {session_id[:12]}...")
                return session_id
            cookie = resp.cookies.get(COOKIE_KEY)
            if cookie:
                print(f"Created anonymous session from cookie")
                return cookie

        raise RuntimeError(f"Could not get session. Status: {resp.status_code}, Body: {resp.text}")


session_id = await get_session_cookie()

#%%
# Step 2: Verify the session works with a single dashboard load sequence
async with httpx.AsyncClient(base_url=BASE_URL, cookies={COOKIE_KEY: session_id}) as client:
    # 1. GET /rest/me
    resp = await client.get("/rest/me")
    print(f"GET /rest/me: status={resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  user_id={data.get('id', 'N/A')}, email={data.get('email', 'N/A')}")

    # 2. GET /rest/collections
    resp = await client.get("/rest/collections")
    print(f"GET /rest/collections: status={resp.status_code}")
    collection_ids: list[str] = []
    if resp.status_code == 200:
        collections = resp.json()
        collection_ids = [c["id"] for c in collections]
        print(f"  Found {len(collection_ids)} collections")

    if collection_ids:
        # 3. POST /rest/collections/permissions
        resp = await client.post(
            "/rest/collections/permissions",
            json={"collection_ids": collection_ids},
        )
        print(f"POST /rest/collections/permissions: status={resp.status_code}")

        # 4. POST /rest/collections/counts (batched)
        for i in range(0, len(collection_ids), COUNTS_BATCH_SIZE):
            batch = collection_ids[i : i + COUNTS_BATCH_SIZE]
            resp = await client.post(
                "/rest/collections/counts",
                json={"collection_ids": batch},
            )
            print(f"POST /rest/collections/counts (batch {i // COUNTS_BATCH_SIZE + 1}): status={resp.status_code}")

    print("\nSingle dashboard load sequence OK")

#%%
# Step 3: Load test — simulate concurrent dashboard page loads
import asyncio
from dataclasses import dataclass, field


@dataclass
class EndpointStats:
    """Latency stats for a single endpoint."""

    name: str
    latencies_ms: list[float] = field(default_factory=list)
    success: int = 0
    failed: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, status_code: int, latency_ms: float, error: str | None = None) -> None:
        self.latencies_ms.append(latency_ms)
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
        if 200 <= status_code < 300:
            self.success += 1
        else:
            self.failed += 1
            if error:
                self.errors.append(error)

    def record_exception(self, latency_ms: float, error: str) -> None:
        self.latencies_ms.append(latency_ms)
        self.failed += 1
        self.errors.append(error)

    @property
    def total(self) -> int:
        return self.success + self.failed

    def _percentile(self, p: int) -> float:
        if not self.latencies_ms:
            return 0
        s = sorted(self.latencies_ms)
        idx = min(int(len(s) * p / 100), len(s) - 1)
        return s[idx]

    @property
    def p50(self) -> float:
        return self._percentile(50)

    @property
    def p95(self) -> float:
        return self._percentile(95)

    @property
    def p99(self) -> float:
        return self._percentile(99)

    @property
    def avg(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0


@dataclass
class DashboardLoadResult:
    """Aggregate results for a dashboard load test run."""

    page_loads: int = 0
    page_load_latencies_ms: list[float] = field(default_factory=list)
    endpoint_stats: dict[str, EndpointStats] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0

    def get_stats(self, name: str) -> EndpointStats:
        if name not in self.endpoint_stats:
            self.endpoint_stats[name] = EndpointStats(name=name)
        return self.endpoint_stats[name]

    @property
    def duration_s(self) -> float:
        return self.end_time - self.start_time

    @property
    def page_loads_per_s(self) -> float:
        return self.page_loads / self.duration_s if self.duration_s > 0 else 0

    def _page_percentile(self, p: int) -> float:
        if not self.page_load_latencies_ms:
            return 0
        s = sorted(self.page_load_latencies_ms)
        idx = min(int(len(s) * p / 100), len(s) - 1)
        return s[idx]

    def summary(self) -> str:
        lines = [
            "=" * 80,
            "DASHBOARD LOAD TEST RESULTS",
            "=" * 80,
            f"Page loads:      {self.page_loads}",
            f"Duration:        {self.duration_s:.2f}s",
            f"Throughput:      {self.page_loads_per_s:.1f} page loads/s",
            "",
            "End-to-end page load latency (ms):",
            f"  avg:  {sum(self.page_load_latencies_ms) / len(self.page_load_latencies_ms):.1f}" if self.page_load_latencies_ms else "  avg:  N/A",
            f"  p50:  {self._page_percentile(50):.1f}",
            f"  p95:  {self._page_percentile(95):.1f}",
            f"  p99:  {self._page_percentile(99):.1f}",
            f"  max:  {max(self.page_load_latencies_ms):.1f}" if self.page_load_latencies_ms else "  max:  N/A",
            "",
            "Per-endpoint breakdown:",
            f"  {'Endpoint':<35} {'Reqs':>5} {'Fail':>5} {'Avg':>8} {'P50':>8} {'P95':>8} {'P99':>8}",
            f"  {'-' * 75}",
        ]
        for name in ["GET /rest/me", "GET /rest/collections", "POST /rest/collections/permissions", "POST /rest/collections/counts"]:
            stats = self.endpoint_stats.get(name)
            if stats and stats.total > 0:
                lines.append(
                    f"  {name:<35} {stats.total:>5} {stats.failed:>5} "
                    f"{stats.avg:>7.1f} {stats.p50:>7.1f} {stats.p95:>7.1f} {stats.p99:>7.1f}"
                )
        # Show any errors grouped by endpoint
        has_errors = False
        for name in ["GET /rest/me", "GET /rest/collections", "POST /rest/collections/permissions", "POST /rest/collections/counts"]:
            stats = self.endpoint_stats.get(name)
            if stats and stats.errors:
                has_errors = True
                lines.append(f"\n  Errors for {name} ({stats.failed} failed / {stats.total} total):")
                # Show status code distribution for failures
                error_codes = {k: v for k, v in stats.status_codes.items() if k < 200 or k >= 300}
                if error_codes:
                    lines.append(f"    Status codes: {dict(sorted(error_codes.items()))}")
                for err in stats.errors[:5]:
                    lines.append(f"    - {err}")
                if len(stats.errors) > 5:
                    lines.append(f"    ... and {len(stats.errors) - 5} more errors")
        if not has_errors:
            lines.append("\n  No errors recorded.")
        lines.append("=" * 80)
        return "\n".join(lines)


def _format_http_error(endpoint: str, resp: httpx.Response, latency_ms: float) -> str:
    """Format a detailed error message from an HTTP response."""
    parts = [
        f"[{endpoint}] HTTP {resp.status_code}",
        f"latency={latency_ms:.0f}ms",
    ]

    # Include useful response headers
    for header in ("retry-after", "x-request-id", "x-correlation-id", "content-type", "server"):
        val = resp.headers.get(header)
        if val:
            parts.append(f"{header}={val}")

    # Include response body (up to 500 chars)
    body = resp.text[:500].strip()
    if body:
        parts.append(f"body={body}")

    return " | ".join(parts)


async def simulate_dashboard_load(
    client: httpx.AsyncClient,
    result: DashboardLoadResult,
) -> None:
    """Simulate a single user loading the dashboard page."""
    page_t0 = time.perf_counter()

    # 1. GET /rest/me
    me_stats = result.get_stats("GET /rest/me")
    t0 = time.perf_counter()
    try:
        resp = await client.get("/rest/me")
        latency = (time.perf_counter() - t0) * 1000
        me_stats.record(resp.status_code, latency, _format_http_error("GET /rest/me", resp, latency) if resp.status_code != 200 else None)
        if resp.status_code != 200:
            # Can't proceed without auth
            result.page_load_latencies_ms.append((time.perf_counter() - page_t0) * 1000)
            result.page_loads += 1
            return
    except Exception as e:
        me_stats.record_exception((time.perf_counter() - t0) * 1000, f"[GET /rest/me] {type(e).__name__}: {e}")
        result.page_load_latencies_ms.append((time.perf_counter() - page_t0) * 1000)
        result.page_loads += 1
        return

    # 2. GET /rest/collections
    coll_stats = result.get_stats("GET /rest/collections")
    t0 = time.perf_counter()
    collection_ids: list[str] = []
    try:
        resp = await client.get("/rest/collections")
        latency = (time.perf_counter() - t0) * 1000
        coll_stats.record(resp.status_code, latency, _format_http_error("GET /rest/collections", resp, latency) if resp.status_code != 200 else None)
        if resp.status_code == 200:
            collection_ids = [c["id"] for c in resp.json()]
    except Exception as e:
        coll_stats.record_exception((time.perf_counter() - t0) * 1000, f"[GET /rest/collections] {type(e).__name__}: {e}")

    if not collection_ids:
        result.page_load_latencies_ms.append((time.perf_counter() - page_t0) * 1000)
        result.page_loads += 1
        return

    # 3 & 4 run in parallel: permissions + sequential count batches
    async def fetch_permissions() -> None:
        perm_stats = result.get_stats("POST /rest/collections/permissions")
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                "/rest/collections/permissions",
                json={"collection_ids": collection_ids},
            )
            latency = (time.perf_counter() - t0) * 1000
            perm_stats.record(resp.status_code, latency, _format_http_error("POST /rest/collections/permissions", resp, latency) if resp.status_code != 200 else None)
        except Exception as e:
            perm_stats.record_exception((time.perf_counter() - t0) * 1000, f"[POST /rest/collections/permissions] {type(e).__name__}: {e}")

    async def fetch_counts_sequential() -> None:
        counts_stats = result.get_stats("POST /rest/collections/counts")
        for i in range(0, len(collection_ids), COUNTS_BATCH_SIZE):
            batch = collection_ids[i : i + COUNTS_BATCH_SIZE]
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    "/rest/collections/counts",
                    json={"collection_ids": batch},
                )
                latency = (time.perf_counter() - t0) * 1000
                counts_stats.record(resp.status_code, latency, _format_http_error("POST /rest/collections/counts", resp, latency) if resp.status_code != 200 else None)
            except Exception as e:
                counts_stats.record_exception((time.perf_counter() - t0) * 1000, f"[POST /rest/collections/counts] {type(e).__name__}: {e}")

    await asyncio.gather(fetch_permissions(), fetch_counts_sequential())

    result.page_load_latencies_ms.append((time.perf_counter() - page_t0) * 1000)
    result.page_loads += 1


async def load_test_dashboard(
    session_id: str,
    num_concurrent: int = NUM_CONCURRENT,
    num_waves: int = NUM_WAVES,
    delay_between_waves: float = DELAY_BETWEEN_WAVES,
) -> DashboardLoadResult:
    result = DashboardLoadResult()

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        cookies={COOKIE_KEY: session_id},
        timeout=httpx.Timeout(60.0),
    ) as client:
        result.start_time = time.perf_counter()

        for wave in range(num_waves):
            tasks = [simulate_dashboard_load(client, result) for _ in range(num_concurrent)]
            await asyncio.gather(*tasks)

            if wave < num_waves - 1:
                await asyncio.sleep(delay_between_waves)

            done = (wave + 1) * num_concurrent
            total = num_waves * num_concurrent
            print(f"  Wave {wave + 1}/{num_waves} done ({done}/{total} page loads)", end="\r")

        result.end_time = time.perf_counter()
        print()

    return result


print(f"Starting dashboard load test: {NUM_CONCURRENT} concurrent x {NUM_WAVES} waves = {NUM_CONCURRENT * NUM_WAVES} total page loads\n")
result = await load_test_dashboard(session_id)
print(result.summary())

#%%


# Print all errors from the load test
print("\n" + "=" * 90)
print("ERRORS SUMMARY")
print("=" * 90)

has_errors = False
for endpoint_name, stats in result.endpoint_stats.items():
    if stats.errors:
        has_errors = True
        print(f"\n{endpoint_name}:")
        for error_msg in stats.errors:
            print(f"  {error_msg}")

if not has_errors:
    print("\nNo errors recorded.")

print("=" * 90)



#%%
# Step 4 (optional): Ramp-up test — gradually increase concurrency
print("Running ramp-up test...\n")

concurrency_levels = [1, 5, 10, 25, 50]
ramp_results: list[tuple[int, DashboardLoadResult]] = []

for concurrency in concurrency_levels:
    print(f"Testing with concurrency={concurrency}...")
    r = await load_test_dashboard(session_id, num_concurrent=concurrency, num_waves=3, delay_between_waves=0.2)
    ramp_results.append((concurrency, r))
    avg_page = sum(r.page_load_latencies_ms) / len(r.page_load_latencies_ms) if r.page_load_latencies_ms else 0
    total_failed = sum(s.failed for s in r.endpoint_stats.values())
    print(f"  -> {r.page_loads_per_s:.1f} pages/s, avg page={avg_page:.0f}ms, failed reqs={total_failed}\n")

print("\n" + "=" * 90)
print(f"{'Concurrency':>12} {'Pages/s':>8} {'Avg(ms)':>8} {'P50(ms)':>8} {'P95(ms)':>8} {'P99(ms)':>8} {'Failed':>7}")
print("-" * 90)
for conc, r in ramp_results:
    avg = sum(r.page_load_latencies_ms) / len(r.page_load_latencies_ms) if r.page_load_latencies_ms else 0
    p50 = r._page_percentile(50)
    p95 = r._page_percentile(95)
    p99 = r._page_percentile(99)
    failed = sum(s.failed for s in r.endpoint_stats.values())
    print(f"{conc:>12} {r.page_loads_per_s:>8.1f} {avg:>8.0f} {p50:>8.0f} {p95:>8.0f} {p99:>8.0f} {failed:>7}")
print("=" * 90)

# Per-endpoint breakdown across concurrency levels
print(f"\nPer-endpoint P95 latency across concurrency levels:")
print(f"{'Concurrency':>12}", end="")
endpoint_names = ["GET /rest/me", "GET /rest/collections", "POST /rest/collections/permissions", "POST /rest/collections/counts"]
for name in endpoint_names:
    short = name.split("/")[-1]
    print(f" {short:>12}", end="")
print()
print("-" * (12 + 13 * len(endpoint_names)))
for conc, r in ramp_results:
    print(f"{conc:>12}", end="")
    for name in endpoint_names:
        stats = r.endpoint_stats.get(name)
        if stats and stats.total > 0:
            print(f" {stats.p95:>11.0f}", end="")
        else:
            print(f" {'N/A':>11}", end="")
    print()
print("=" * (12 + 13 * len(endpoint_names)))

# %%
