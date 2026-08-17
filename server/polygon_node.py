"""
ocean.vaked.dev — Polygon Sovereign Node Status
Read-only JSON-RPC probes for the Polygon PoS sovereign node.

Exposes:
  GET /polygon/status — chain id, sync progress, latest block
  GET /polygon/vaked  — VAKED ERC-20 contract state (supply + operator balances)
Never 5xx: an unreachable node / RPC error returns HTTP 200 with
error="node unreachable" so the status page always renders.
Read-only only — no arbitrary JSON-RPC proxying.
"""

import os
import time
from decimal import Decimal, localcontext
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter

router = APIRouter()

DEFAULT_RPC_URL = "http://polygon-node.tail2870dc.ts.net:8545"
CACHE_TTL_SEC = 15.0
RPC_TIMEOUT_SEC = 5.0

# VAKED ERC-20 (Polygon PoS, 18 decimals)
VAKED_CONTRACT = "0x2Ae7DA713A2c8527AF70825C0F79632AF2e2ae4A"
VAKED_DECIMALS = 18
VAKED_OPERATOR = "0xbcA9E062c3dD3a2f198C917e77b9F8D5F03fCF3D"
VAKED_DEPLOYER = "0x6fCf4790cC08eE4887d8b47e42A5a9Af8FAc8aBa"

# Per-endpoint cache of the last successful probe, keyed by route name:
#   {route: {"ts": float, "result": Dict[str, Any]}}
_cache: Dict[str, Dict[str, Any]] = {}


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    """Return a fresh (< CACHE_TTL_SEC) cached probe for key, else None."""
    entry = _cache.get(key)
    if entry is not None and (time.monotonic() - entry["ts"]) < CACHE_TTL_SEC:
        return entry["result"]
    return None


def _cache_set(key: str, result: Dict[str, Any]) -> None:
    """Store a successful probe result under key."""
    _cache[key] = {"ts": time.monotonic(), "result": result}


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
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    req_id: int,
    params: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """POST a single JSON-RPC call; raise on HTTP or JSON-RPC-level errors."""
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": [] if params is None else params,
    }
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

    # Serve a fresh cached probe so page refreshes don't hammer the node.
    cached = _cache_get("status")
    if cached is not None:
        return {**cached, "cached": True}

    try:
        result = _build_result(url, await _probe_node(url))
    except Exception:
        return _unreachable(url)

    _cache_set("status", result)
    return {**result, "cached": False}


def _wei_to_vaked(wei: int) -> str:
    """Exact wei -> VAKED (18 decimals) human amount as a short decimal string.

    Uses Decimal arithmetic (never float): totalSupply_wei / 1e18 is a plain
    decimal-point shift, exact within a localcontext sized for the integer
    part plus 18 fractional digits. Decimal division already yields the
    minimal form (no trailing zeros), so 50 * 10**18 wei renders as "50"
    (not "50.0"). NOTE: do not run .normalize() on the result — normalize()
    executes under the *default* 28-digit context and would round quotients
    with more than 28 significant digits.
    """
    if wei is None:
        return None
    with localcontext() as ctx:
        ctx.prec = len(str(abs(wei))) + VAKED_DECIMALS + 1
        vaked = Decimal(wei) / (Decimal(10) ** VAKED_DECIMALS)
    return format(vaked, "f")


def _balance_of_data(address: str) -> str:
    """Encode balanceOf(address) calldata: 0x70a08231 + 32-byte left-padded address."""
    cleaned = address[2:] if address.startswith("0x") else address
    return "0x70a08231" + cleaned.lower().zfill(64)


async def _probe_vaked(url: str) -> Dict[str, Any]:
    """Read VAKED contract state via eth_call at the current head block."""
    timeout = aiohttp.ClientTimeout(total=RPC_TIMEOUT_SEC)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        block = await _rpc_call(session, url, "eth_blockNumber", 1)
        block_hex = block["result"]
        supply = await _rpc_call(
            session,
            url,
            "eth_call",
            2,
            params=[{"to": VAKED_CONTRACT, "data": "0x18160ddd"}, block_hex],
        )
        operator = await _rpc_call(
            session,
            url,
            "eth_call",
            3,
            params=[{"to": VAKED_CONTRACT, "data": _balance_of_data(VAKED_OPERATOR)}, block_hex],
        )
        deployer = await _rpc_call(
            session,
            url,
            "eth_call",
            4,
            params=[{"to": VAKED_CONTRACT, "data": _balance_of_data(VAKED_DEPLOYER)}, block_hex],
        )
    return {
        "block": block_hex,
        "supply": supply["result"],
        "operator": operator["result"],
        "deployer": deployer["result"],
    }


def _build_vaked_result(probe: Dict[str, Any]) -> Dict[str, Any]:
    """Map raw eth_call responses into the public /polygon/vaked contract."""
    total_supply = _hex_to_int(probe["supply"])
    operator_wei = _hex_to_int(probe["operator"])
    deployer_wei = _hex_to_int(probe["deployer"])

    return {
        "contract": VAKED_CONTRACT,
        "totalSupply": total_supply,
        "totalSupplyVaked": _wei_to_vaked(total_supply) if total_supply is not None else None,
        "balances": {
            VAKED_OPERATOR: {
                "wei": operator_wei,
                "vaked": _wei_to_vaked(operator_wei) if operator_wei is not None else None,
            },
            VAKED_DEPLOYER: {
                "wei": deployer_wei,
                "vaked": _wei_to_vaked(deployer_wei) if deployer_wei is not None else None,
            },
        },
        "blockNumber": _hex_to_int(probe["block"]),
        "error": None,
    }


def _vaked_unreachable() -> Dict[str, Any]:
    """Graceful degraded payload for /polygon/vaked — never 5xx."""
    return {
        "contract": VAKED_CONTRACT,
        "totalSupply": None,
        "totalSupplyVaked": None,
        "balances": None,
        "blockNumber": None,
        "error": "node unreachable",
        "cached": False,
    }


@router.get("/polygon/vaked")
async def polygon_vaked() -> Dict[str, Any]:
    url = _rpc_url()

    # Serve a fresh cached probe so page refreshes don't hammer the node.
    cached = _cache_get("vaked")
    if cached is not None:
        return {**cached, "cached": True}

    try:
        result = _build_vaked_result(await _probe_vaked(url))
    except Exception:
        return _vaked_unreachable()

    _cache_set("vaked", result)
    return {**result, "cached": False}
