"""会话历史三级压缩策略

控制多轮对话的 token 开销，避免 AI 幻觉：
1. 滑动窗口：保留最近 N 轮完整对话
2. 摘要压缩：超出窗口的历史生成摘要
3. 上下文引用：已选择上下文项以简短描述形式注入，不重复全文
"""
from typing import List, Dict, Optional


# 滑动窗口大小：保留最近几轮完整对话（1轮 = 1条user + 1条assistant）
SLIDING_WINDOW_ROUNDS = 4

# 单条消息字符上限
MAX_MESSAGE_CHARS = 5000

# 总 prompt 字符上限（约 4000 tokens）
MAX_TOTAL_CHARS = 15000


def compress_conversation(
    messages: List[Dict[str, str]],
    historical_summary: Optional[str] = None
) -> Dict:
    """压缩会话历史，返回用于 LLM 的消息列表

    Args:
        messages: 完整的会话消息列表，每条格式 {"role": "user"/"assistant", "content": "..."}
        historical_summary: 之前已生成的历史摘要（从数据库读取）

    Returns:
        {
            "messages": 压缩后的消息列表（可直接传给 LLM），
            "new_summary": 需要更新保存的新摘要（无变更时为 None），
            "total_chars": 压缩后总字符数
        }
    """
    # 截断过长的单条消息
    truncated = []
    for msg in messages:
        content = msg.get("content", "")
        if len(content) > MAX_MESSAGE_CHARS:
            content = content[:MAX_MESSAGE_CHARS] + "\n...(消息过长已截断)"
        truncated.append({"role": msg["role"], "content": content})

    # 计算窗口范围：保留最近 N 轮（2*N 条消息）
    window_size = SLIDING_WINDOW_ROUNDS * 2
    total_msgs = len(truncated)

    if total_msgs <= window_size:
        # 未超出窗口，无需压缩
        return {
            "messages": truncated,
            "new_summary": None,
            "total_chars": sum(len(m["content"]) for m in truncated)
        }

    # 分割：窗口外的历史 + 窗口内的近期对话
    split_point = total_msgs - window_size
    old_messages = truncated[:split_point]
    recent_messages = truncated[split_point:]

    # 生成新摘要：合并旧摘要 + 旧消息的关键信息
    new_summary = _generate_summary(old_messages, historical_summary)

    # 构建压缩后的消息列表：摘要作为 system 消息 + 近期对话
    compressed = []
    if new_summary:
        compressed.append({
            "role": "system",
            "content": f"[历史对话摘要]\n{new_summary}"
        })
    compressed.extend(recent_messages)

    total_chars = sum(len(m["content"]) for m in compressed)

    return {
        "messages": compressed,
        "new_summary": new_summary,
        "total_chars": total_chars
    }


def _generate_summary(
    old_messages: List[Dict[str, str]],
    existing_summary: Optional[str]
) -> str:
    """从旧消息中提取关键信息生成摘要

    注意：这里采用规则式摘要（非 AI 生成），避免额外 API 调用开销。
    提取每轮用户问题和 AI 回复的核心结论。
    """
    summary_parts = []

    if existing_summary:
        summary_parts.append(existing_summary)

    # 从旧消息中提取每轮的要点
    for i in range(0, len(old_messages), 2):
        user_msg = old_messages[i] if i < len(old_messages) else None
        ai_msg = old_messages[i + 1] if i + 1 < len(old_messages) else None

        if user_msg and user_msg["role"] == "user":
            # 提取用户问题前100字符
            question = user_msg["content"][:100]
            if len(user_msg["content"]) > 100:
                question += "..."
            summary_parts.append(f"用户问: {question}")

        if ai_msg and ai_msg["role"] == "assistant":
            # 提取 AI 回复前150字符作为结论摘要
            answer = ai_msg["content"][:150]
            if len(ai_msg["content"]) > 150:
                answer += "..."
            summary_parts.append(f"AI答: {answer}")

    # 限制摘要总长度
    result = "\n".join(summary_parts)
    if len(result) > 2000:
        result = result[:2000] + "\n...(摘要已截断)"

    return result
