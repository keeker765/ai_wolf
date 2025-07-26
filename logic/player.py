# player.py
from typing import Dict, Any, Union, Tuple

from logic.game_utils import Role, call_dashscope


def get_player_role_from_log(player_id: int, player_roles: Dict[int, Dict[str, Any]]) -> str:
    """获取指定玩家的角色"""
    if player_id in player_roles:
        return player_roles[player_id]["role"].name
    raise ValueError(f"Player {player_id} not found in log")


class Player:
    def __init__(self, player_id: int, role: Role):
        self.player_id = player_id
        self.role = role
        self.alive = True
        self.checked_players = {}  # 预言家查过的玩家 {"A": "好人"}
        self.last_guarded = -1  # 守卫上一轮守护的玩家

        self.model = "deepseek-r1"
        self.reasoning_contents = {}


    def filter_receive_info(self, game_log: Dict[str, Any]) -> Dict[str, Any]:
        """
        过滤游戏日志，只返回玩家可以看到的信息
        """
        filtered_info = {}
        for key, value in game_log.items():
            # 初始化第一层键
            if key not in filtered_info:
                filtered_info[key] = {}

            if key.startswith("night"):
                for thinking_vote, contents in value.items():
                    if thinking_vote.startswith(self.role.name.lower()) or thinking_vote == "death_log":
                        # 只保留当前玩家的发言和投票
                        filtered_info[key][thinking_vote] = contents



            # 白天发言和投票结果所有玩家可见
            elif key.startswith("day"):
                filtered_info[key] = value.copy()

            # 结果日志所有玩家可见，但隐藏角色信息
            elif key.startswith("result-"):
                # 注意这里匹配新的键格式 "result-<阶段>-<轮次>"
                if self.role == Role.WOLF:
                    # 狼人可以看到狼人
                    filtered_info[key] = {}
                    for a_or_d, role_values in value.items():
                        filtered_info[key][a_or_d] = {
                            pid: role if role == "WOLF" else "隐藏"
                            for pid, role in role_values.items()
                        }

                else:
                    filtered_info[key] = {
                        "alive": {pid: "隐藏" for pid in value["alive"]},
                        "dead": {pid: "隐藏" for pid in value["dead"]}
                    }

        return filtered_info

    def generate_speech(self, game_log: Dict[str, Any]) -> str:
        """
        生成发言内容
        """
        filtered_info = self.filter_receive_info(game_log)

        content = {
            "type": "speech",
            "memory": filtered_info,
            "role": self.role.name,
            "player_id": self.player_id,
            "checked_players": self.checked_players
        }

        return call_dashscope(content, model=self.model)["response"]["thinking"]

    def decide_vote(self, game_log: Dict[str, Any]) -> tuple[str, int]:
        """
        决定投票给谁
        """
        filtered_info = self.filter_receive_info(game_log)

        content = {
            "type": "decision",
            "memory": filtered_info,
            "role": self.role.name,
            "player_id": self.player_id,
            "question_guide": "你要投票放逐谁？请仔细分析发言和游戏历史。"
        }
        res = call_dashscope(content, model=self.model)["response"]

        return res["thinking"], res["target"]

    def action_thinking_result(self, game_log: Dict[str, Any]) -> tuple[Any, dict[Any, str]] | tuple[Any, Any]:
        """
        进行行动思考，返回思考结果和目标
        """
        question = ""
        role_map = {
            Role.WOLF.name: "狼人",
            Role.SEER.name: "预言家",
            Role.GUARD.name: "守卫"
        }



        if self.role == Role.GUARD:
            question = "作为守卫，你今晚要守护谁？不能连续两晚守护同一人。"
        elif self.role == Role.SEER:
            question = "作为预言家，你今晚要查验谁的身份？"
        elif self.role == Role.WOLF:
            question = f"作为{role_map[self.role.name]}，你今晚要刀杀谁？请与其他狼人讨论后决定。"

        content = {
            "type": "thinking and target",
            "memory": self.filter_receive_info(game_log),
            "role": self.role.name,
            "player_id": self.player_id,
            "last_guarded": self.last_guarded,
            "checked_players": self.checked_players,
            "question_guide": question,
            "reasoning_contents": self.reasoning_contents
        }

        res = call_dashscope(content, model=self.model)["response"]
        reasoning_content = res.get("reasoning_content", None)

        if reasoning_content:
            _k = ""
            for key in game_log.keys():
                if key.startswith("night") or key.startswith("day") or key.startswith("vot"):
                    _k = key

            self.reasoning_contents[_k] = reasoning_content
        target = res['target']

        if self.role == Role.SEER:
            # 预言家获得目标的真实身份
            target_role = get_player_role_from_log(target, game_log["player_roles"])
            role_set = "好人" if target_role in ["VILLAGER", "GUARD", "SEER"] else "坏人"
            self.checked_players[target] = role_set
            return res['thinking'], {target: role_set}

        elif self.role == Role.GUARD:
            self.last_guarded = target

        return res['thinking'], target
