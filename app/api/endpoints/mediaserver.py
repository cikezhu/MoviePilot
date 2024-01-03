from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app import schemas
from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.mediaserver import MediaServerChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.metainfo import MetaInfo
from app.core.security import verify_token
from app.db import get_db
from app.db.mediaserver_oper import MediaServerOper
from app.db.models import MediaServerItem
from app.schemas import MediaType, NotExistMediaInfo

router = APIRouter()


@router.get("/play/{itemid}", summary="在线播放")
def play_item(itemid: str) -> Any:
    """
    跳转媒体服务器播放页面
    """
    if not itemid:
        return
    if not settings.MEDIASERVER:
        return
    mediaserver = settings.MEDIASERVER.split(",")[0]
    play_url = MediaServerChain().get_play_url(server=mediaserver, item_id=itemid)
    # 重定向到play_url
    if not play_url:
        return
    return RedirectResponse(url=play_url)


@router.get("/exists", summary="本地是否存在", response_model=schemas.Response)
def exists(title: str = None,
           year: int = None,
           mtype: str = None,
           tmdbid: int = None,
           season: int = None,
           db: Session = Depends(get_db),
           _: schemas.TokenPayload = Depends(verify_token)) -> Any:
    """
    判断本地是否存在
    """
    meta = MetaInfo(title)
    if not season:
        season = meta.begin_season
    # 返回对象
    ret_info = {}
    # 本地数据库是否存在
    exist: MediaServerItem = MediaServerOper(db).exists(
        title=meta.name, year=year, mtype=mtype, tmdbid=tmdbid, season=season
    )
    if not exist:
        # 服务器是否存在
        mediainfo = MediaInfo()
        mediainfo.from_dict({
            "title": meta.name,
            "year": year or meta.year,
            "type": mtype or meta.type,
            "tmdb_id": tmdbid,
            "season": season
        })
        exist: schemas.ExistMediaInfo = MediaServerChain().media_exists(
            mediainfo=mediainfo
        )
        if exist:
            ret_info = {
                "id": exist.itemid
            }
    else:
        ret_info = {
            "id": exist.item_id
        }
    return schemas.Response(success=True if exist else False, data={
        "item": ret_info
    })


@router.post("/notexists", summary="查询缺失媒体信息", response_model=List[schemas.NotExistMediaInfo])
def not_exists(media_in: schemas.MediaInfo,
               _: schemas.TokenPayload = Depends(verify_token)) -> Any:
    """
    查询缺失媒体信息
    """
    # 媒体信息
    meta = MetaInfo(title=media_in.title)
    mtype = MediaType(media_in.type) if media_in.type else None
    if mtype:
        meta.type = mtype
    if media_in.season:
        meta.begin_season = media_in.season
        meta.type = MediaType.TV
    if media_in.year:
        meta.year = media_in.year
    if media_in.tmdb_id or media_in.douban_id:
        mediainfo = MediaChain().recognize_media(meta=meta, mtype=mtype,
                                                 tmdbid=media_in.tmdb_id, doubanid=media_in.douban_id)
    else:
        mediainfo = MediaChain().recognize_by_meta(metainfo=meta)
    # 查询缺失信息
    if not mediainfo:
        raise HTTPException(status_code=404, detail="媒体信息不存在")
    mediakey = mediainfo.tmdb_id or mediainfo.douban_id
    exist_flag, no_exists = DownloadChain().get_no_exists_info(meta=meta, mediainfo=mediainfo)
    if mediainfo.type == MediaType.MOVIE:
        # 电影已存在时返回空列表，存在时返回空对像列表
        return [] if exist_flag else [NotExistMediaInfo()]
    elif no_exists and no_exists.get(mediakey):
        # 电视剧返回缺失的剧集
        return list(no_exists.get(mediakey).values())
    return []