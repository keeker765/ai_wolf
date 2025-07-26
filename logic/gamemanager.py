# gamemanager.py
import random
import time
from typing import Dict, Any, List

from logic.game_utils import Role
from logic.player import Player


def _resolve_votes(votes: Dict[int, List[int]]) -> int:
    """解决投票冲突，返回得票最多的玩家ID"""
    if not votes:
        return -1  # 没有投票

    # 统计有效票数
    vote_counts = {}
    for target, voters in votes.items():
        if target >= 0:  # 只统计有效目标
            vote_counts[target] = vote_counts.get(target, 0) + len(voters)

    if not vote_counts:
        return -1  # 所有投票都无效

    max_votes = max(vote_counts.values())
    candidates = [pid for pid, count in vote_counts.items() if count == max_votes]

    # 处理平票情况
    return random.choice(candidates) if candidates else -1


def _record_vote(vote_dict: Dict[int, List[int]], target_id: int, voter_id: int):
    """记录投票信息"""
    if target_id != -1:
        if target_id not in vote_dict:
            vote_dict[target_id] = []
        vote_dict[target_id].append(voter_id)


class GameManager:
    def __init__(self, verbose: bool = True):
        self.players: List[Player] = []
        self.current_phase = "NIGHT"
        self.current_round = 0
        self.game_log: Dict[str, Any] = {}
        self.verbose = verbose
        self.setup_game()

    def setup_game(self):
        """初始化游戏，分配角色并创建玩家"""
        roles = [Role.WOLF, Role.WOLF, Role.VILLAGER, Role.VILLAGER, Role.SEER, Role.GUARD]
        random.shuffle(roles)

        # 创建玩家角色字典
        self.game_log["player_roles"] = {
            i: {
                "player_id": i,
                "role": roles[i]
            } for i in range(6)
        }

        # 初始化玩家对象
        for i in range(6):
            self.players.append(Player(i, roles[i]))

        if self.verbose:
            print("=== 游戏开始 ===")
            print("初始角色分配: ", [player.role.name for player in self.players])
        self._log_round_result()

    def handle_night_phase(self):
        """处理夜间阶段的行动"""
        night_key = f"night-{self.current_round}"
        self.game_log[night_key] = {
            "wolf_sayings": {},
            "wolf_vote": {},
            "seer_analysis": "",
            "seer_predict": {},
            "guard_analysis": "",
            "guard_protect": -1,
        }

        # 处理狼人投票
        werewolves = [p for p in self.players if p.role == Role.WOLF and p.alive]
        if werewolves:
            wolf_votes = {}
            for wolf in werewolves:
                thinking, target_id = wolf.action_thinking_result(self.game_log)
                self.game_log[night_key]["wolf_sayings"][wolf.player_id] = thinking
                _record_vote(wolf_votes, target_id, wolf.player_id)
                if self.verbose:
                    print(f"狼人 {wolf.player_id} 表达：{thinking}, 投票给: {target_id}")
            candidate = _resolve_votes(wolf_votes)
            final_target = candidate if candidate else -1
            if self.verbose:
                print(f"狼人最终目标: {final_target}，获得的票来自: ", wolf_votes.get(final_target, []))
            self.game_log[night_key]["wolf_vote"][final_target] = wolf_votes.get(final_target, [])

        # 处理预言家行动
        seers = [p for p in self.players if p.role == Role.SEER and p.alive]
        if seers:
            seer = seers[0]
            analysis, prediction = seer.action_thinking_result(self.game_log)
            self.game_log[night_key]["seer_analysis"] = analysis
            target_id = list(prediction.keys())[0]
            self.game_log[night_key]["seer_predict"][target_id] = prediction[target_id]
            if self.verbose:
                print(f"预言家{seer.player_id}分析: {analysis}, 预言: {prediction}")

        # 处理守卫行动
        guards = [p for p in self.players if p.role == Role.GUARD and p.alive]
        if guards:
            guard = guards[0]
            analysis, protect_target = guard.action_thinking_result(self.game_log)
            self.game_log[night_key]["guard_analysis"] = analysis
            self.game_log[night_key]["guard_protect"] = protect_target
            if self.verbose:
                print(f"守卫{guard.player_id}分析: {analysis}, 保护: {protect_target}")

        # 处理夜间死亡结果
        death_log = []
        wolf_target = next(iter(self.game_log[night_key]["wolf_vote"]), -1)
        guard_target = self.game_log[night_key]["guard_protect"]

        if wolf_target != -1 and wolf_target != guard_target:
            # 狼人目标没有被守护，死亡
            if self.players[wolf_target].alive:
                self.players[wolf_target].alive = False
                death_log.append(wolf_target)
                if self.verbose:
                    print(f"玩家 {wolf_target} 在夜晚被狼人杀害。")

        self.game_log[night_key]["death_log"] = death_log
        self._log_round_result()

    def handle_day_phase(self):
        """处理白天阶段的发言"""
        day_key = f"day-{self.current_round}"
        self.game_log[day_key] = {
            "heard_sayings": {},
            "final_vote": {}
        }

        # 随机顺序发言
        alive_players = [p for p in self.players if p.alive]

        for player in alive_players:
            speech = player.generate_speech(self.game_log)
            self.game_log[day_key]["heard_sayings"][player.player_id] = speech
            if self.verbose:
                print(f"玩家{player.role.name} {player.player_id} 发言: {speech}")

    def handle_voting_phase(self):
        """处理投票阶段"""
        day_key = f"day-{self.current_round}"
        votes = {}

        for player in self.players:
            if player.alive:
                vote_thinking, vote_result = player.decide_vote(self.game_log)
                if self.verbose:
                    print(f"玩家 {player.player_id} 思考: {vote_thinking}, 投票给: {vote_result}")
                _record_vote(votes, vote_result, player.player_id)

        candidates = _resolve_votes(votes)
        exiled_player = -1

        if candidates:
            exiled_player = candidates

        if exiled_player != -1:
            if self.players[exiled_player].alive:
                self.players[exiled_player].alive = False
                self.game_log[day_key]["death_log"] = [exiled_player]
                if self.verbose:
                    print(f"玩家 {exiled_player} 被投票放逐。")
        else:
            self.game_log[day_key]["death_log"] = []
            if self.verbose:
                print("本轮投票无人被放逐。")

        self._log_round_result()

    def _log_round_result(self):
        """记录当前游戏状态作为结果"""
        result_key = f"result-{self.current_phase}-{self.current_round}"
        self.game_log[result_key] = {
            "alive": {p.player_id: p.role.name for p in self.players if p.alive},
            "dead": {p.player_id: p.role.name for p in self.players if not p.alive}
        }
        if self.verbose:
            print(f"轮次结束后的存亡状态: 存活玩家: {self.game_log[result_key]['alive']}, 已故玩家: {self.game_log[result_key]['dead']}")

    def check_game_end(self) -> bool:
        """检查游戏是否结束及胜负条件"""
        werewolf_count = sum(1 for p in self.players if p.role == Role.WOLF and p.alive)
        villager_count = sum(1 for p in self.players if p.role != Role.WOLF and p.alive)
        god_count = sum(1 for p in self.players if p.role == Role.SEER and p.alive) + sum(1 for p in self.players if p.role == Role.GUARD and p.alive)

        if werewolf_count == 0:
            if self.verbose:
                print("好人阵营胜利！")
            return True

        if villager_count == 0 or god_count == 0:
            if self.verbose:
                print("狼人阵营胜利！")
            return True

        return False

    def run(self):
        """运行游戏主循环"""
        # 初始化后记录结果
        self._log_round_result()

        while not self.check_game_end():
            if self.verbose:
                print(f"\n=== 第 {self.current_round + 1} 轮开始 ===")
                print(f"当前阶段: {self.current_phase}")

            if self.current_phase == "NIGHT":
                self.handle_night_phase()
                self.current_phase = "DAY"
                time.sleep(5)
            elif self.current_phase == "DAY":
                self.handle_day_phase()
                self.current_phase = "VOTING"
                time.sleep(5)
            elif self.current_phase == "VOTING":
                self.handle_voting_phase()
                self.current_phase = "NIGHT"
                self.current_round += 1
                time.sleep(5)

            # 检查游戏是否结束
            if self.check_game_end():
                break

        # 游戏结束，打印最终结果
        if self.verbose:
            print("\n=== 游戏结束 ===")
            print("最终存活玩家:")
            for player in self.players:
                if player.alive:
                    print(f"玩家 {player.player_id} ({player.role.name})")

            print("\n最终死亡玩家:")
            for player in self.players:
                if not player.alive:
                    print(f"玩家 {player.player_id} ({player.role.name})")


if __name__ == "__main__":
    game = GameManager(verbose=True)
    game.run()
