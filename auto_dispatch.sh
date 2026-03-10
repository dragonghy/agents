#!/bin/bash
# auto_dispatch.sh — 自动检查 Leantime 新任务并唤醒空闲 agent
#
# ⚠️ DEPRECATED: 此脚本的功能已内置到 agents-mcp daemon 中。
# daemon 启动后会自动每 30 秒执行 dispatch 循环。
# 此脚本仅保留作为 daemon 不可用时的 fallback。
# 正常使用请通过 restart_all_agents.sh 管理 daemon。
#
# 用法:
#   ./auto_dispatch.sh              # 运行一次
#   ./auto_dispatch.sh --loop       # 每 30 秒循环运行
#
# 逻辑:
#   对每个 agent:
#     1. 查询 Leantime 是否有分配给该 agent 的待处理任务（排除已完成和已归档）
#     2. 检查 agent 的 tmux pane 是否空闲
#     3. 两者都满足时，发送唤醒消息

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${ROOT_DIR}/agent-config.py"

TMUX_SESSION="$(python3 "$CONFIG" tmux-session)"
LEANTIME_URL="$(python3 "$CONFIG" leantime url)"
LEANTIME_API_KEY="$(python3 "$CONFIG" leantime api_key)"
LEANTIME_PROJECT_ID="$(python3 "$CONFIG" leantime project_id)"
AGENTS="$(python3 "$CONFIG" list-agents | tr '\n' ' ')"
INTERVAL=30

log() {
  echo "[$(date '+%H:%M:%S')] $*"
}

# 查询 Leantime 中某个 agent 是否有可执行任务
# 只检查 status=3（新增）和 status=4（进行中）
# 忽略 status=1（已锁定）、0（已完成）、-1（已归档）
has_pending_tasks() {
  local agent="$1"
  local count
  count=$(curl -s -X POST "${LEANTIME_URL}/api/jsonrpc" \
    -H "Content-Type: application/json" \
    -H "x-api-key: ${LEANTIME_API_KEY}" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"leantime.rpc.Tickets.Tickets.getAll\",\"params\":{\"searchCriteria\":{\"currentProject\":${LEANTIME_PROJECT_ID}}},\"id\":1}" \
    2>/dev/null \
    | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tickets = json.loads(data['result']) if isinstance(data.get('result'), str) else data.get('result', [])
    count = sum(1 for t in tickets if t.get('tags') and 'agent:${agent}' in t['tags'] and t.get('status') in (3, 4))
    print(count)
except:
    print(0)
" 2>/dev/null)
  [[ "$count" -gt 0 ]]
}

# 检查 agent 的 tmux window 是否存在
window_exists() {
  local agent="$1"
  tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$agent"
}

# 判断 agent 是否空闲
is_idle() {
  local agent="$1"
  local output
  output=$(tmux capture-pane -t "${TMUX_SESSION}:${agent}" -p 2>/dev/null | grep -v '^[[:space:]]*$' | tail -10)

  # 先排除工作中的特征
  if echo "$output" | grep -qE 'Running…|Wandering…|esc to interrupt'; then
    return 1
  fi

  # 再检查是否有空闲提示符
  if echo "$output" | grep -q '^❯'; then
    return 0
  fi

  # 状态不明
  return 1
}

# 发送唤醒消息
# 重要：文本和 Enter 必须分开发送，用 -l 发送 literal 文本，中间等待 2 秒
dispatch_agent() {
  local agent="$1"
  tmux send-keys -l -t "${TMUX_SESSION}:${agent}" \
    "你有待处理的 Leantime 任务。请查询分配给你的任务（tags 包含 agent:${agent}，status=3,4）并执行。"
  sleep 2
  tmux send-keys -t "${TMUX_SESSION}:${agent}" Enter
}

# 检查所有 blocked ticket 的依赖是否已全部完成
# 如果全部依赖完成，自动将 ticket 从 blocked(1) 改为 new(3)
check_blocked_deps() {
  LEANTIME_URL="$LEANTIME_URL" LEANTIME_API_KEY="$LEANTIME_API_KEY" LEANTIME_PROJECT_ID="$LEANTIME_PROJECT_ID" \
  python3 - <<'PYEOF'
import json, os, re, sys, urllib.request

LEANTIME_URL = os.environ["LEANTIME_URL"]
LEANTIME_API_KEY = os.environ["LEANTIME_API_KEY"]
LEANTIME_PROJECT_ID = os.environ["LEANTIME_PROJECT_ID"]

def rpc_call(method, params=None):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}).encode()
    req = urllib.request.Request(
        f"{LEANTIME_URL}/api/jsonrpc",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": LEANTIME_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    result = data.get("result", [])
    if isinstance(result, str):
        result = json.loads(result)
    return result

try:
    # Fetch all tickets in project
    tickets = rpc_call("leantime.rpc.Tickets.Tickets.getAll", {"searchCriteria": {"currentProject": int(LEANTIME_PROJECT_ID)}})
    if not isinstance(tickets, list):
        sys.exit(0)

    # Build id->status lookup
    status_map = {}
    for t in tickets:
        tid = t.get("id")
        if tid is not None:
            status_map[int(tid)] = int(t.get("status", 99))

    # Find blocked tickets (status=1) with DEPENDS_ON
    for t in tickets:
        if int(t.get("status", 99)) != 1:
            continue
        desc = t.get("description") or ""
        # Match DEPENDS_ON: #12, #34 (supports HTML entities like &#35; for #)
        match = re.search(r'DEPENDS_ON:\s*((?:#\d+|&#35;\d+)(?:\s*,\s*(?:#\d+|&#35;\d+))*)', desc)
        if not match:
            continue
        dep_ids = [int(x) for x in re.findall(r'(\d+)', match.group(1))]
        if not dep_ids:
            continue

        # Check if all dependencies are done (0) or archived (-1)
        all_done = all(status_map.get(d, 99) in (0, -1) for d in dep_ids)
        if not all_done:
            continue

        # Unblock: read-modify-write to status=3 (New)
        ticket_id = int(t["id"])
        current = rpc_call("leantime.rpc.Tickets.Tickets.getTicket", {"id": ticket_id})
        if current:
            current["status"] = 3
            current["id"] = ticket_id
            rpc_call("leantime.rpc.Tickets.Tickets.updateTicket", {"values": current})
            print(f"  解锁 #{ticket_id} (依赖 {dep_ids} 已全部完成)")
except Exception as e:
    print(f"  依赖检查异常: {e}", file=sys.stderr)
PYEOF
}

# 单次检查所有 agent
check_all() {
  local dispatched=0
  local summary=""

  # 先检查依赖解锁
  log "检查 blocked ticket 依赖..."
  check_blocked_deps

  for agent in $AGENTS; do
    # 1. 有待处理任务吗？
    if ! has_pending_tasks "$agent"; then
      summary+=" ${agent}:无任务"
      continue
    fi

    # 2. tmux window 存在吗？
    if ! window_exists "$agent"; then
      summary+=" ${agent}:无窗口"
      log "${agent}: tmux window 不存在，跳过"
      continue
    fi

    # 3. 空闲吗？
    if ! is_idle "$agent"; then
      summary+=" ${agent}:工作中"
      log "${agent}: 正在工作中，跳过"
      continue
    fi

    # 4. 唤醒
    summary+=" ${agent}:已唤醒"
    dispatched=$((dispatched + 1))
    log "${agent}: 空闲且有待处理任务，发送唤醒消息"
    dispatch_agent "$agent"
  done

  log "检查完毕 |${summary} | 本轮唤醒: ${dispatched}"
}

# --- Main ---

if [[ "${1:-}" == "--loop" ]]; then
  log "自动 dispatch 启动，每 ${INTERVAL} 秒检查一次 (Ctrl+C 退出)"
  while true; do
    check_all
    sleep "$INTERVAL"
  done
else
  check_all
fi
