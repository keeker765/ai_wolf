# main.py
import json
import random
import uuid
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from logic.gamemanager import GameManager
from logic.game_utils import Role

# 创建FastAPI应用
app = FastAPI(title="狼人杀游戏API", description="狼人杀游戏的HTTP接口")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 游戏实例存储
games: Dict[str, GameManager] = {}

# 玩家连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[int, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, game_id: str, player_id: int):
        await websocket.accept()
        if game_id not in self.active_connections:
            self.active_connections[game_id] = {}
        self.active_connections[game_id][player_id] = websocket

    def disconnect(self, game_id: str, player_id: int):
        if game_id in self.active_connections and player_id in self.active_connections[game_id]:
            del self.active_connections[game_id][player_id]
            if not self.active_connections[game_id]:
                del self.active_connections[game_id]

    async def broadcast(self, game_id: str, message: dict):
        if game_id in self.active_connections:
            for player_id, connection in self.active_connections[game_id].items():
                player_message = self.filter_message_for_player(message, player_id, game_id)
                await connection.send_json(player_message)

    def filter_message_for_player(self, message: dict, player_id: int, game_id: str) -> dict:
        # 根据玩家角色过滤信息
        if game_id not in games:
            return message
            
        game = games[game_id]
        if player_id >= len(game.players):
            return message
            
        player = game.players[player_id]
        
        # 复制消息以避免修改原始消息
        filtered_message = message.copy()
        
        # 如果消息包含游戏状态，过滤角色信息
        if "game_state" in filtered_message:
            game_state = filtered_message["game_state"].copy()
            
            # 过滤玩家角色信息，只显示自己的角色
            if "players" in game_state:
                filtered_players = []
                for p in game_state["players"]:
                    p_copy = p.copy()
                    # 如果不是当前玩家，隐藏角色
                    if p["player_id"] != player_id:
                        # 狼人可以看到其他狼人的身份
                        if player.role == Role.WOLF and p["role"] == "WOLF":
                            pass  # 保持狼人角色可见
                        else:
                            p_copy["role"] = "UNKNOWN"  # 对其他玩家隐藏角色
                    filtered_players.append(p_copy)
                game_state["players"] = filtered_players
            
            filtered_message["game_state"] = game_state
            
        return filtered_message

manager = ConnectionManager()

# 数据模型
class GameCreate(BaseModel):
    verbose: bool = False

class PlayerAction(BaseModel):
    action_type: str  # "vote", "guard", "seer", "speech"
    target_id: Optional[int] = None
    content: Optional[str] = None

# API路由
@app.get("/")
async def get_root():
    return {"message": "欢迎使用狼人杀游戏API"}

@app.post("/games", response_model=Dict[str, Any])
async def create_game(game_data: GameCreate):
    game_id = str(uuid.uuid4())
    games[game_id] = GameManager(verbose=game_data.verbose)
    
    # 返回游戏信息
    return {
        "game_id": game_id,
        "message": "游戏创建成功",
        "players": [
            {
                "player_id": player.player_id,
                "role": player.role.name,
                "alive": player.alive
            } for player in games[game_id].players
        ],
        "current_phase": games[game_id].current_phase,
        "current_round": games[game_id].current_round
    }

@app.get("/games/{game_id}", response_model=Dict[str, Any])
async def get_game(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    game = games[game_id]
    
    return {
        "game_id": game_id,
        "players": [
            {
                "player_id": player.player_id,
                "role": player.role.name,
                "alive": player.alive
            } for player in game.players
        ],
        "current_phase": game.current_phase,
        "current_round": game.current_round,
        "game_log": game.game_log
    }

@app.get("/games/{game_id}/player/{player_id}", response_model=Dict[str, Any])
async def get_player_info(game_id: str, player_id: int):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    game = games[game_id]
    
    if player_id < 0 or player_id >= len(game.players):
        raise HTTPException(status_code=404, detail="玩家不存在")
    
    player = game.players[player_id]
    
    # 过滤游戏日志，只返回玩家可见的信息
    filtered_log = player.filter_receive_info(game.game_log)
    
    return {
        "player_id": player.player_id,
        "role": player.role.name,
        "alive": player.alive,
        "checked_players": player.checked_players if player.role == Role.SEER else {},
        "last_guarded": player.last_guarded if player.role == Role.GUARD else -1,
        "game_log": filtered_log
    }

@app.post("/games/{game_id}/player/{player_id}/action", response_model=Dict[str, Any])
async def player_action(game_id: str, player_id: int, action: PlayerAction):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    game = games[game_id]
    
    if player_id < 0 or player_id >= len(game.players):
        raise HTTPException(status_code=404, detail="玩家不存在")
    
    player = game.players[player_id]
    
    if not player.alive:
        raise HTTPException(status_code=400, detail="玩家已死亡，无法执行操作")
    
    # 根据当前游戏阶段和玩家角色验证操作
    if game.current_phase == "NIGHT":
        if action.action_type == "guard" and player.role == Role.GUARD:
            if action.target_id == player.last_guarded:
                raise HTTPException(status_code=400, detail="不能连续两晚守护同一玩家")
            # 处理守卫操作
            night_key = f"night-{game.current_round}"
            if night_key not in game.game_log:
                game.game_log[night_key] = {
                    "wolf_sayings": {},
                    "wolf_vote": {},
                    "seer_analysis": "",
                    "seer_predict": {},
                    "guard_analysis": "",
                    "guard_protect": -1,
                }
            game.game_log[night_key]["guard_protect"] = action.target_id
            player.last_guarded = action.target_id
            return {"message": f"守卫成功保护玩家 {action.target_id}"}
            
        elif action.action_type == "seer" and player.role == Role.SEER:
            # 处理预言家操作
            target_id = action.target_id
            if target_id < 0 or target_id >= len(game.players):
                raise HTTPException(status_code=400, detail="目标玩家不存在")
                
            target_player = game.players[target_id]
            role_set = "好人" if target_player.role in [Role.VILLAGER, Role.GUARD, Role.SEER] else "坏人"
            
            night_key = f"night-{game.current_round}"
            if night_key not in game.game_log:
                game.game_log[night_key] = {
                    "wolf_sayings": {},
                    "wolf_vote": {},
                    "seer_analysis": "",
                    "seer_predict": {},
                    "guard_analysis": "",
                    "guard_protect": -1,
                }
            
            game.game_log[night_key]["seer_predict"][target_id] = role_set
            player.checked_players[target_id] = role_set
            
            return {"message": f"预言家查验结果: 玩家 {target_id} 是 {role_set}"}
            
        elif action.action_type == "wolf" and player.role == Role.WOLF:
            # 处理狼人操作
            target_id = action.target_id
            if target_id < 0 or target_id >= len(game.players):
                raise HTTPException(status_code=400, detail="目标玩家不存在")
                
            night_key = f"night-{game.current_round}"
            if night_key not in game.game_log:
                game.game_log[night_key] = {
                    "wolf_sayings": {},
                    "wolf_vote": {},
                    "seer_analysis": "",
                    "seer_predict": {},
                    "guard_analysis": "",
                    "guard_protect": -1,
                }
            
            # 记录狼人发言
            if action.content:
                game.game_log[night_key]["wolf_sayings"][player_id] = action.content
            
            # 记录狼人投票
            if "wolf_vote" not in game.game_log[night_key]:
                game.game_log[night_key]["wolf_vote"] = {}
                
            if target_id not in game.game_log[night_key]["wolf_vote"]:
                game.game_log[night_key]["wolf_vote"][target_id] = []
                
            game.game_log[night_key]["wolf_vote"][target_id].append(player_id)
            
            return {"message": f"狼人选择了攻击目标: 玩家 {target_id}"}
        else:
            raise HTTPException(status_code=400, detail="当前阶段或角色不允许此操作")
            
    elif game.current_phase == "DAY":
        if action.action_type == "speech":
            # 处理白天发言
            if not action.content:
                raise HTTPException(status_code=400, detail="发言内容不能为空")
                
            day_key = f"day-{game.current_round}"
            if day_key not in game.game_log:
                game.game_log[day_key] = {
                    "heard_sayings": {},
                    "final_vote": {}
                }
                
            game.game_log[day_key]["heard_sayings"][player_id] = action.content
            
            return {"message": "发言已记录"}
        else:
            raise HTTPException(status_code=400, detail="当前阶段不允许此操作")
            
    elif game.current_phase == "VOTING":
        if action.action_type == "vote":
            # 处理投票
            target_id = action.target_id
            if target_id != -1 and (target_id < 0 or target_id >= len(game.players)):
                raise HTTPException(status_code=400, detail="目标玩家不存在")
                
            if target_id != -1 and not game.players[target_id].alive:
                raise HTTPException(status_code=400, detail="不能投票给已死亡的玩家")
                
            day_key = f"day-{game.current_round}"
            if day_key not in game.game_log:
                game.game_log[day_key] = {
                    "heard_sayings": {},
                    "final_vote": {}
                }
                
            if "final_vote" not in game.game_log[day_key]:
                game.game_log[day_key]["final_vote"] = {}
                
            if target_id not in game.game_log[day_key]["final_vote"]:
                game.game_log[day_key]["final_vote"][target_id] = []
                
            game.game_log[day_key]["final_vote"][target_id].append(player_id)
            
            return {"message": f"玩家 {player_id} 投票给了玩家 {target_id}"}
        else:
            raise HTTPException(status_code=400, detail="当前阶段不允许此操作")
    else:
        raise HTTPException(status_code=400, detail="未知游戏阶段")

@app.post("/games/{game_id}/next-phase", response_model=Dict[str, Any])
async def advance_game_phase(game_id: str):
    if game_id not in games:
        raise HTTPException(status_code=404, detail="游戏不存在")
    
    game = games[game_id]
    
    # 保存当前阶段和轮次
    current_phase = game.current_phase
    current_round = game.current_round
    
    # 根据当前阶段执行相应的处理
    if current_phase == "NIGHT":
        # 处理夜晚结束，进入白天
        process_night_results(game)
        game.current_phase = "DAY"
    elif current_phase == "DAY":
        # 白天发言结束，进入投票阶段
        game.current_phase = "VOTING"
    elif current_phase == "VOTING":
        # 投票结束，处理投票结果，进入下一轮夜晚
        process_voting_results(game)
        game.current_phase = "NIGHT"
        game.current_round += 1
    
    # 检查游戏是否结束
    game_ended = game.check_game_end()
    
    # 广播游戏状态更新
    await manager.broadcast(game_id, {
        "type": "phase_change",
        "previous_phase": current_phase,
        "current_phase": game.current_phase,
        "current_round": game.current_round,
        "game_state": get_game_state(game),
        "game_ended": game_ended
    })
    
    return {
        "previous_phase": current_phase,
        "current_phase": game.current_phase,
        "current_round": game.current_round,
        "game_ended": game_ended,
        "winner": get_winner(game) if game_ended else None
    }

def process_night_results(game: GameManager):
    """处理夜晚阶段的结果"""
    night_key = f"night-{game.current_round}"
    
    # 确保夜晚记录存在
    if night_key not in game.game_log:
        game.game_log[night_key] = {
            "wolf_sayings": {},
            "wolf_vote": {},
            "seer_analysis": "",
            "seer_predict": {},
            "guard_analysis": "",
            "guard_protect": -1,
            "death_log": []
        }
    
    # 处理狼人投票
    wolf_votes = game.game_log[night_key].get("wolf_vote", {})
    
    # 统计票数
    vote_counts = {}
    for target, voters in wolf_votes.items():
        if target != -1:  # 忽略弃权
            vote_counts[target] = len(voters)
    
    # 找出得票最多的玩家
    wolf_target = -1
    if vote_counts:
        max_votes = max(vote_counts.values())
        candidates = [pid for pid, count in vote_counts.items() if count == max_votes]
        wolf_target = random.choice(candidates) if candidates else -1
    
    # 获取守卫保护的目标
    guard_target = game.game_log[night_key].get("guard_protect", -1)
    
    # 处理夜间死亡
    death_log = []
    if wolf_target != -1 and wolf_target != guard_target:
        # 狼人目标没有被守护，死亡
        if wolf_target < len(game.players) and game.players[wolf_target].alive:
            game.players[wolf_target].alive = False
            death_log.append(wolf_target)
    
    game.game_log[night_key]["death_log"] = death_log
    game._log_round_result()

def process_voting_results(game: GameManager):
    """处理投票阶段的结果"""
    day_key = f"day-{game.current_round}"
    
    # 确保白天记录存在
    if day_key not in game.game_log:
        game.game_log[day_key] = {
            "heard_sayings": {},
            "final_vote": {},
            "death_log": []
        }
    
    # 处理投票
    votes = game.game_log[day_key].get("final_vote", {})
    
    # 统计票数
    vote_counts = {}
    for target, voters in votes.items():
        if target != -1:  # 忽略弃权
            vote_counts[target] = len(voters)
    
    # 找出得票最多的玩家
    exiled_player = -1
    if vote_counts:
        max_votes = max(vote_counts.values())
        candidates = [pid for pid, count in vote_counts.items() if count == max_votes]
        exiled_player = random.choice(candidates) if candidates else -1
    
    # 处理放逐
    if exiled_player != -1:
        if exiled_player < len(game.players) and game.players[exiled_player].alive:
            game.players[exiled_player].alive = False
            game.game_log[day_key]["death_log"] = [exiled_player]
    else:
        game.game_log[day_key]["death_log"] = []
    
    game._log_round_result()

def get_game_state(game: GameManager) -> dict:
    """获取当前游戏状态"""
    return {
        "players": [
            {
                "player_id": player.player_id,
                "role": player.role.name,
                "alive": player.alive
            } for player in game.players
        ],
        "current_phase": game.current_phase,
        "current_round": game.current_round,
        "game_log": game.game_log
    }

def get_winner(game: GameManager) -> str:
    """获取游戏胜利方"""
    werewolf_count = sum(1 for p in game.players if p.role == Role.WOLF and p.alive)
    villager_count = sum(1 for p in game.players if p.role != Role.WOLF and p.alive)
    god_count = sum(1 for p in game.players if (p.role == Role.SEER or p.role == Role.GUARD) and p.alive)
    
    if werewolf_count == 0:
        return "好人阵营"
    
    if villager_count == 0 or god_count == 0:
        return "狼人阵营"
    
    return "游戏尚未结束"

# WebSocket连接
@app.websocket("/ws/{game_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: int):
    if game_id not in games:
        await websocket.accept()
        await websocket.send_json({"error": "游戏不存在"})
        await websocket.close()
        return
    
    game = games[game_id]
    
    if player_id < 0 or player_id >= len(game.players):
        await websocket.accept()
        await websocket.send_json({"error": "玩家不存在"})
        await websocket.close()
        return
    
    await manager.connect(websocket, game_id, player_id)
    
    try:
        # 发送初始游戏状态
        send_json = {
            "type": "init",
            "player_id": player_id,
            "role": game.players[player_id].role.name,
            "game_state": manager.filter_message_for_player({"game_state": get_game_state(game)}, player_id, game_id)["game_state"]
        }
        await websocket.send_json(send_json)
        
        while True:
            data = await websocket.receive_text()
            # 这里可以处理从客户端接收的消息
            # 目前我们只是简单地广播消息
            await manager.broadcast(game_id, {"type": "message", "player_id": player_id, "message": data})
    except WebSocketDisconnect:
        manager.disconnect(game_id, player_id)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 提供HTML页面
@app.get("/play", response_class=HTMLResponse)
async def get_game_page():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)