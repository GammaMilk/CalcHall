import asyncio
import errno
import json
import random
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from pydantic import BaseModel

app = FastAPI()

class L:
    @classmethod
    def w(cls, *args, **kwargs):
        print("\033[43mWARNING\033[0m:\033[33m", *args, "\033[0m", **kwargs)
    @classmethod
    def i(cls, *args, **kwargs):
        print("\033[42mINFO\033[0m:\033[32m", *args, "\033[0m", **kwargs)
    @classmethod
    def d(cls, *args, **kwargs):
        print("\033[44mDEBUG\033[0m:\033[34m", *args, "\033[0m", **kwargs)
    @classmethod
    def e(cls, *args, **kwargs):
        print("\033[41mERROR\033[0m:\033[31m", *args, "\033[0m", **kwargs)

class Player:
    openid:str=None
    nickName: str=None
    session: WebSocket=None
    p: int=None
    def __str__(self) -> str:
        return f"Player({self.openid}, {self.nickName}, {self.p})"


class RoomMsg(BaseModel):
    errno: int
    errmsg: str
    anotherNickName: str=None
    anotherAdd: int
    
class HallMsg(BaseModel):
    errno: int
    errmsg: str
    msg: str
    roomid: int=None
    
class ClientMsg(BaseModel):
    p: int
    code: int

class Room:
    def __init__(self, p1:Player, p2:Player) -> None:
        self.p1=p1
        self.p2=p2
        self._id=-1
        self.p1c:int=0
        self.p2c:int=0
        self.leave=False
        self.p1.session = None
        self.p2.session = None
        
    async def broadCast(self, message):
        await self.p1.session.send_text(message)
        await self.p2.session.send_text(message)
    async def sendAnotherCount(self, p:Player):
        if p == self.p1:
            await self.p1.session.send_text(
                RoomMsg(errno=0,errmsg='',anotherAdd=self.p2c, anotherNickName=self.p2.nickName).json()
            )
        elif p == self.p2:
            await self.p2.session.send_text(
                RoomMsg(errno=0,errmsg='',anotherAdd=self.p1c, anotherNickName=self.p1.nickName).json()
            )
    async def playerAddNum(self, p:Player):
        if p == self.p1:
            self.p1c+=1
            if self.p2.session:
                await self.p2.session.send_text(
                    RoomMsg(errno=0,errmsg='',anotherAdd=self.p1c, anotherNickName=self.p1.nickName).json()
                )
        else:
            self.p2c+=1
            if self.p1.session:
                await self.p1.session.send_text(
                    RoomMsg(errno=0,errmsg='',anotherAdd=self.p2c, anotherNickName=self.p2.nickName).json()
                )
    async def disconnect(self, p:Player):
        L.w(f"Player {p} disconnected")
        if not self.leave:
            self.leave=True
            rm.leave(self._id)
            if p == self.p1:
                await self.p2.session.send_text(
                    RoomMsg(errno=errno.ECONNRESET,errmsg='对方已离开',anotherAdd=0).json()
                )
                await self.p2.session.close()
            else:
                await self.p1.session.send_text(
                    RoomMsg(errno=errno.ECONNRESET,errmsg='对方已离开',anotherAdd=0).json()
                )
                await self.p1.session.close()
class FakeSession:
    def send_text(self, message):
        pass
    def close(self):
        pass
    
class FakeRoom(Room):
    def __init__(self, p1:Player):
        fakePlayer = Player()
        fakePlayer.nickName = "Bot"
        fakePlayer.openid = "Bot"+f"{random.randint(0, 1000000)}"
        fakePlayer.session = FakeSession()
        super().__init__(p1, fakePlayer)
        self.bot = asyncio.create_task(self.botRunner())
    async def botRunner(self):
        # 每隔一段时间自己加一分
        while 1:
            await self.playerAddNum(self.p2)
            await asyncio.sleep(random.randint(7,12))
            if self.p2c >= 20 or self.leave or not self.p1.session:
                await self.broadCast(
                    RoomMsg(errno=errno.ECONNRESET,errmsg='机器人已离开',anotherAdd=0).json()
                )
                await self.p2.session.close()
                return
class RoomManager:
    def __init__(self) -> None:
        self.rooms: List[Room] = []
    def assign(self, p1:Player, p2:Player):
        _p1 = Player()
        _p1.openid = p1.openid
        _p1.nickName = p1.nickName
        _p2 = Player()
        _p2.openid = p2.openid
        _p2.nickName = p2.nickName
        self.rooms.append(Room(_p1,_p2))
        self.rooms[-1]._id = len(self.rooms)-1
        return self.rooms[-1]._id
    def assign_bot(self, p1:Player):
        # assign a fake player as a bot to play with the player
        _p1 = Player()
        _p1.openid = p1.openid
        _p1.nickName = p1.nickName
        self.rooms.append(FakeRoom(_p1))
        self.rooms[-1]._id = len(self.rooms)-1
        return self.rooms[-1]._id
    def leave(self, roomID:int):
        self.rooms.pop(roomID)
    def getRoom(self, roomID:int):
        return self.rooms[roomID]
    def checkRoomID(self, roomID:int):
        return roomID < len(self.rooms)
    def checkPlayerInRooms(self, openid:str):
        for room in self.rooms:
            if room.p1.openid == openid or room.p2.openid == openid:
                return True
        return False

rm = RoomManager()


class WaitingHall:
    def __init__(self) -> None:
        self.q: List[Player] = []
    async def connect(self, session: WebSocket):
        await session.accept()
    async def onMessage(self, session: WebSocket, message: str):
        assert(session is not None)
        # msg is json, contains openid, nickName
        jmsg = json.loads(message)
        
        player = Player()
        player.nickName = jmsg['nickName']
        player.openid = jmsg['openid']
        player.session = session
        L.w(player)
        if self.q.__len__() > 0 and player.openid == self.q[0].openid:
            L.w('重复连接')
            return
        # check if player in room
        if rm.checkPlayerInRooms(player.openid):
            L.w('重复连接')
            msg = HallMsg(errno=0, errmsg='', msg='matching', roomid=None)
            await session.send_text(msg.json())
            return
        if len(self.q) == 0:
            player.p = 1
            L.w(f"{player.nickName}({player.openid})加入等待队列")
            self.q.append(player)
            msg = HallMsg(errno=0, errmsg='', msg='matching', roomid=None)
            await session.send_text(msg.json())
            await asyncio.sleep(8)
            if player in self.q:
                self.q.remove(player)
                L.w(f"{player.nickName}({player.openid})匹配超时,分配机器人")
                roomid = rm.assign_bot(player)
                msg = HallMsg(errno=0, errmsg='', msg='matched', roomid=roomid)
                await session.send_text(msg.json())
            # await self.broadcast(f'{player.nickName} is waiting for a match')
        else:
            
            player.p = 2
            anotherPlayer = self.q.pop()
            
            roomid = rm.assign(anotherPlayer,player)
            L.w(f"{player.nickName}({player.openid})匹配成功. 对手是{anotherPlayer.nickName}({anotherPlayer.openid})")
            L.w(f"房间号是{roomid}")
            msg = HallMsg(errno=0, errmsg='', msg='match success', roomid=roomid)
            # await self.broadcast(f'{anotherPlayer.nickName} vs {player.nickName}')
            await player.session.send_text(msg.json())
            await anotherPlayer.session.send_text(msg.json())
                
    def disconnect(self, session: WebSocket):
        # check if in q
        for i in range(len(self.q)):
            if self.q[i].session == session:
                self.q.pop(i)
                break
    async def broadcast(self, message: str):
        for p in self.q:
            msg = HallMsg(errno=0, errmsg='', msg=message)
            await p.session.send_text(msg.json())
            
hall = WaitingHall()

@app.websocket("/ws/hall")
async def ws_hall_endpoint(
    websocket: WebSocket
):
    await hall.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await hall.onMessage(websocket, data)
    except WebSocketDisconnect:
        hall.disconnect(websocket)

@app.websocket("/ws/room/{roomID}/{openid}")
async def ws_room_endpoint(
    ws: WebSocket,
    roomID: int,
    openid: str
):
    if not rm.checkRoomID(roomID):
        await ws.close()
        return
    room = rm.getRoom(roomID)
    if room.p1.openid == openid:
        player = room.p1
        room.p1.session = ws
    elif room.p2.openid == openid:
        player = room.p2
        room.p2.session = ws
    else:
        await ws.close()
        return
    await ws.accept()
    await room.sendAnotherCount(player)
    try:
        while True:
            data = await ws.receive_text()
            if data == 'add':
                await room.playerAddNum(player)
    except WebSocketDisconnect:
        await room.disconnect(player)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=1667)
    