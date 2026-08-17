"""
ocean.vaked.dev — Polygon Sovereign Node Status
Read-only JSON-RPC health probe for the Polygon PoS sovereign node.

Exposes GET /polygon/status: chain id, sync progress, and latest block.
Never 5xx: an unreachable node / RPC error returns HTTP 200 with
error="node unreachable" so the status page always renders.
Read-only only — no arbitrary JSON-RPC proxying.
"""

import os
import time
from typing import Any, Dict, Optional

import aiohttp
from fastapi import APIRouter

router = APIRouter()

DEFAULT_RPC_URL = "http://polygon-node.tail2870dc.ts.net:8545"
CACHE_TTL_SEC = 15.0
RPC_TIMEOUT_SEC = 5.0

# Last successful probe, keyed by monotonic timestamp:
#   {"ts": float, "result": Dict[str, Any]}
_cache: Dict[str, Any] = {}


def _rpc_url() -> str:
    """Node RPC URL, overridable via the POLYGON_RPC_URL env var."""
    return os.environ.get("POLYGON_RPC_URL", DEFAULT_RPC_URL)


def _hex_to_int(value: Any) -> Optional[int]:
    """Convert a hex (0x...) or decimal JSON-RPC quantity to int; None if unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str) and value.startswith("0x"):
            return int(value, 16)
        return int(value)
    except (TypeError, ValueError):
        return None


async def _rpc_call(
    session: aiohttp.ClientSession, url: str, method: str, req_id: int
) -> Dict[str, Any]:
    """POST a single JSON-RPC call; raise on HTTP or JSON-RPC-level errors."""
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": []}
    async with session.post(url, json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json()
    if not isinstance(data, dict) or data.get("error") is not None:
        raise ValueError(
            f"JSON-RPC error from {method}: "
            f"{data.get('error') if isinstance(data, dict) else data}"
        )
    return data


async def _probe_node(url: str) -> Dict[str, Any]:
    """Sequentially probe net_version, eth_syncing, eth_blockNumber."""
    timeout = aiohttp.ClientTimeout(total=RPC_TIMEOUT_SEC)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        net = await _rpc_call(session, url, "net_version", 1)
        syncing = await _rpc_call(session, url, "eth_syncing", 2)
        block = await _rpc_call(session, url, "eth_blockNumber", 3)
    return {"net": net, "syncing": syncing, "block": block}


def _build_result(url: str, probe: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw JSON-RPC responses into the public status contract."""
    net = probe["net"].get("result")
    block = probe["block"].get("result")
    sync_state = probe["syncing"].get("result")

    chain_id: Optional[int] = None
    if net is not None:
        try:
            chain_id = int(net)
        except (TypeError, ValueError):
            chain_id = None

    syncing = False
    current_block: Optional[int] = None
    highest_block: Optional[int] = None
    if isinstance(sync_state, dict):
        # eth_syncing returns an object {currentBlock, highestBlock, ...} while syncing
        syncing = True
        current_block = _hex_to_int(sync_state.get("currentBlock"))
        highest_block = _hex_to_int(sync_state.get("highestBlock"))
    elif sync_state is True:
        # Some clients report `true` without progress details
        syncing = True

    return {
        "rpcUrl": url,
        "chainId": chain_id,
        "syncing": syncing,
        "currentBlock": current_block,
        "highestBlock": highest_block,
        "blockNumber": _hex_to_int(block),
        "error": None,
    }


def _unreachable(url: str) -> Dict[str, Any]:
    """Graceful degraded payload — the status page must still render, never 5xx."""
    return {
        "rpcUrl": url,
        "syncing": None,
        "chainId": None,
        "currentBlock": None,
        "highestBlock": None,
        "blockNumber": None,
        "error": "node unreachable",
        "cached": False,
    }


@router.get("/polygon/status")
async def polygon_status() -> Dict[str, Any]:
    url = _rpc_url()
    now = time.monotonic()

    # Serve a fresh cached probe so page refreshes don't hammer the node.
    cached_ts = _cache.get("ts")
    cached_result = _cache.get("result")
    if (
        cached_ts is not None
        and cached_result is not None
        and (now - cached_ts) < CACHE_TTL_SEC
    ):
        return {**cached_result, "cached": True}

    try:
        result = _build_result(url, await _probe_node(url))
    except Exception:
        return _unreachable(url)

    _cache["ts"] = now
    _cache["result"] = result
    return {**result, "cached": False}
