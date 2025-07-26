# game_utils.py
from enum import Enum
from typing import Dict, Any, List, Optional
import random
import json
import dashscope
import os

from config import DASH_SCOPE_API_KEY
from logic.model_config import model_config

# 设置DashScope API密钥
dashscope.api_key = DASH_SCOPE_API_KEY

class Role(str, Enum):
    WOLF = "WOLF"
    VILLAGER = "VILLAGER"
    SEER = "SEER"
    GUARD = "GUARD"

    def __json__(self) -> str:
        return self.value


def format_memory(memory: Dict[str, Any]) -> str:
    """将游戏记忆转换为自然语言描述"""
    description = []

    for key, value in memory.items():
        if key.startswith("result"):
            # 现在键名格式是"result-{round_num}"，没有phase部分
            round_num = key.split("-")[-1]
            alive_players = [f"玩家{pid}({role})" for pid, role in value["alive"].items()]
            dead_players = [f"玩家{pid}({role})" for pid, role in value["dead"].items()] if "dead" in value else []

            desc = f"第{round_num}轮结束：存活玩家: {', '.join(alive_players)}"
            if dead_players:
                desc += f"; 死亡玩家: {', '.join(dead_players)}"
            description.append(desc)

        elif key.startswith("night"):
            round_num = key.split("-")[-1]
            night_desc = f"第{round_num}夜:"

            if "wolf_sayings" in value:
                sayings = [f"玩家{pid}: {text}" for pid, text in value["wolf_sayings"].items()]
                night_desc += f" 狼人讨论: {'; '.join(sayings)}"

            if "wolf_vote" in value:
                for target, voters in value["wolf_vote"].items():
                    if target != -1:
                        voters_list = [f"玩家{vid}" for vid in voters]
                        night_desc += f" 狼人投票: 目标玩家{target} (投票者: {', '.join(voters_list)})"

            if "seer_predict" in value:
                for target, identity in value["seer_predict"].items():
                    night_desc += f" 预言家查验: 玩家{target}是{identity}"

            if "guard_protect" in value and value["guard_protect"] != -1:
                night_desc += f" 守卫守护: 玩家{value['guard_protect']}"

            description.append(night_desc)

        elif key.startswith("day"):
            round_num = key.split("-")[-1]
            day_desc = f"第{round_num}天:"

            if "heard_sayings" in value:
                sayings = [f"玩家{pid}: {text}" for pid, text in value["heard_sayings"].items()]
                day_desc += f" 玩家发言: {'; '.join(sayings)}"

            if "final_vote" in value:
                for target, voters in value["final_vote"].items():
                    if target != -1:
                        voters_list = [f"玩家{vid}" for vid in voters]
                        day_desc += f" 投票结果: 玩家{target}被放逐 (投票者: {', '.join(voters_list)})"

            description.append(day_desc)

    return "\n".join(description)

def call_dashscope(content: Dict[str, Any], model, test=False) -> Dict[str, Any]:
    """
    调用DashScope API，将content解析为自然语言输入，并解析JSON响应
    """
    # 角色映射为中文
    role_map = {
        Role.WOLF.name: "狼人",
        Role.VILLAGER.name: "村民",
        Role.SEER.name: "预言家",
        Role.GUARD.name: "守卫"
    }

    # 获取当前玩家信息
    role = content["role"]
    player_id = content.get("player_id", -1)
    chinese_role = role_map.get(role, role)
    reasoning_contents = content.get("reasoning_contents", {})

    # 构建系统提示
    system_prompt = (
        f"你正在扮演狼人杀游戏中的{chinese_role}角色（玩家{player_id}）。"
        "请基于游戏历史和当前情况，做出符合角色特性的决策。"
        "游戏规则：狼人每晚可以刀杀一名玩家，预言家可以查验一名玩家的身份，"
        "守卫可以守护一名玩家免受狼人杀害（不能连续两晚守护同一人），"
        "村民没有特殊能力。配置为：两狼 两名 一预 一守卫"
        "第0轮代表游戏开始，第1轮代表第一天开始，第2轮代表第二天开始，以此类推。"
        "请你用中文思考中文说话，不要使用英文。"
        "要通过逻辑去思考判断，而不是通过随机选择或者简单的猜测。"
    )

    # 构建用户提示
    user_prompt = f"当前你的角色：{chinese_role}（你的玩家id-- {player_id}）\n"

    # 添加记忆信息
    if "memory" in content:
        user_prompt += "游戏历史记录：\n"
        user_prompt += format_memory(content["memory"])
        # 思考记录
        if reasoning_contents:
            user_prompt += "\n\n 思考记录，以 阶段-天数的形式:\n"
            for key, value in reasoning_contents.items():
                user_prompt += f"\n{key}:\n{value}"
        user_prompt += "\n\n"


    # 添加特定信息
    if "last_guarded" in content and content["last_guarded"] != -1:
        user_prompt += f"你上一轮守护了玩家{content['last_guarded']}。\n"

    if "checked_players" in content:
        checked = [f"玩家{pid}({identity})" for pid, identity in content["checked_players"].items()]
        if checked:
            user_prompt += f"你已查验过的玩家: {', '.join(checked)}\n"

    # 根据操作类型添加指令
    operation_type = content.get("type", "")
    question_guide = content.get("question_guide", "")

    # 添加角色行为指南
    role_behavior = {
        Role.WOLF.name: (
            "作为狼人，你的目标是消灭所有村民和神职角色。"
            "在发言时，尽量伪装成好人，如有机会， 例如发言比较靠前，"
            "就尽量悍跳预言家，混淆视听；"
            "在夜间行动时，与同伴讨论并选择最有威胁的目标刀杀。"
            "你的队友会是WOLF标记的玩家。"
        ),
        Role.VILLAGER.name: (
            "作为村民，你没有特殊能力，需要通过发言和投票找出狼人。"
        ),
        Role.SEER.name: (
            "作为预言家，你每晚可以查验一名玩家的真实身份。"
        ),
        Role.GUARD.name: (
            "作为守卫，你每晚可以守护一名玩家免受狼人杀害。"
            "可以守护自己、预言家或可疑玩家，但不能连续两晚守护同一人。"
        )
    }

    user_prompt += f"\n{role_behavior.get(role, '')}\n"

    # 添加操作类型特定指令
    if operation_type == "speech":
        user_prompt += (
            f"\n现在需要你进行发言。请以{chinese_role}的身份表达你的观点，"
            "分析场上局势，可以怀疑其他玩家，也可以为自己辩护。"
            "发言内容应基于游戏历史和你的角色立场。"
            "直接输出发言内容，不要包含额外说明。"
        )
    elif operation_type == "decision":
        user_prompt += (
            f"\n现在需要你投票决定放逐一名玩家。{question_guide}"
            "请分析场上情况，选择你认为最可疑的玩家进行投票。"
            "在思考后，输出一个数字表示你要投票的玩家ID（0-5）。"
            "弃权选择-1。"
        )
    elif operation_type == "thinking and target":
        user_prompt += (
            f"\n现在是夜间行动阶段。{question_guide}"
            f"你作为{chinese_role}的视角，思考你的行动策略。"
            "请分析场上情况，做出符合你角色能力的决策。"
            "在思考后，输出一个JSON格式的响应："
            '{"thinking": "你的思考过程", "target": 目标玩家ID}'
            "目标玩家ID应为0-5之间的整数，如果没有目标则写-1。"
            "请确保只输出有效的JSON格式，不要包含其他内容。"
        )
    else:
        user_prompt += f"\n{question_guide}"

    if test:
        # 测试模式逻辑
        alive_players = [i for i in range(6)]
        target = -1
        if role == Role.WOLF.name:
            candidates = [p for p in alive_players if p != player_id]
            target = random.choice(candidates) if candidates else -1
        elif role == Role.SEER.name:
            checked_players = content.get("checked_players", {})
            candidates = [p for p in alive_players if p not in checked_players]
            target = random.choice(candidates) if candidates else -1
        elif role == Role.GUARD.name:
            last_guarded = content.get("last_guarded", -1)
            candidates = [p for p in alive_players if p != last_guarded]
            target = random.choice(candidates) if candidates else -1

        thinking = f"[测试模式] {role}选择了玩家 {target}"
        return {"response": {"thinking": thinking, "target": target}}

    try:
        # 调用DashScope API
        def _get_response(retry_times=3):
            for i in range(retry_times):
                response = dashscope.Generation.call(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    **model_config[model]
                )
                # 检查响应状态
                if response.status_code != 200:
                    print(f"DashScope API调用失败: {response.code} - {response.message}")
                else:
                    return response
            else:
                raise Exception(f"DashScope API调用失败: 重试次数达到上限")

        response = _get_response()

        # 获取模型响应内容
        raw_response = response.output.choices[0]['message']['content'].strip()
        reasoning_content = response.output.choices[0]['message'].get('reasoning_content', None)

        # 根据操作类型解析响应
        if operation_type == "thinking and target":
            # 尝试解析JSON格式
            try:
                # 提取JSON部分（可能包含在代码块中）
                json_start = raw_response.find('{')
                json_end = raw_response.rfind('}') + 1
                if json_start != -1 and json_end != -1:
                    json_str = raw_response[json_start:json_end]
                    parsed = json.loads(json_str)
                    return {"response": parsed, "reasoning_content":reasoning_content}
                else:
                    # 如果没有显式JSON，尝试直接解析整个响应
                    parsed = json.loads(raw_response)
                    return {"response": parsed}
            except json.JSONDecodeError as e:
                # 如果JSON解析失败，返回错误信息
                return {
                    "response": {
                        "thinking": f"JSON解析失败: {str(e)}. 原始响应: {raw_response}",
                        "target": -1
                    }
                }

        elif operation_type == "decision":
            # 尝试提取投票目标数字
            for char in raw_response:
                if char.isdigit() and 0 <= int(char) <= 5:
                    return {"response": {"thinking": raw_response, "target": int(char)}}
            # 如果没有找到有效数字
            return {"response": {"thinking": raw_response, "target": -1}}

        else:  # 发言或其他
            return {"response": {"thinking": raw_response, "target": -1}}

    except Exception as e:
        print(f"调用DashScope API失败: {str(e)}")
        # 失败时返回默认值
        return {"response": {"thinking": "思考过程生成失败", "target": -1}}
