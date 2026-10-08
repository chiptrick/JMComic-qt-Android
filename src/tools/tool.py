import base64
import hashlib
import json
import math
import os
import re
import time
from collections import OrderedDict
from urllib.parse import quote

import io
try:
    # lxml 仅用于写 ComicInfo.xml(Element/SubElement/ElementTree)，桌面端继续用它；
    # Android 上 lxml 需要静态 libxml2/libxslt，构建链很脆弱，缺失时用标准库等价实现
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree

from config import config
from config.setting import Setting
from tools import platform_mobile
from tools.langconv import Converter
from tools.log import Log
from tools.status import Status


class CTime(object):
    def __init__(self):
        self._t1 = time.time()

    def Refresh(self, clsName, des='', checkTime=100):
        t2 = time.time()
        diff = int((t2 - self._t1) * 1000)
        if diff >= checkTime:
            text = 'CTime consume:{} ms, {}.{}'.format(diff, clsName, des)
            Log.Warn(text)
        self._t1 = t2
        return diff


def time_me(fn):
    def _wrapper(*args, **kwargs):
        start = time.time()
        rt = fn(*args, **kwargs)
        diff = int((time.time() - start) * 1000)
        if diff >= 100:
            clsName = args[0]
            strLog = 'time_me consume,{} ms, {}.{}'.format(diff, clsName, fn.__name__)
            # Log.w(strLog)
            Log.Warn(strLog)
        return rt

    return _wrapper


class ToolUtil(object):

    @staticmethod
    def DictToUrl(paramDict):
        assert isinstance(paramDict, dict)
        data = ''
        for k, v in paramDict.items():
            data += quote(str(k)) + '=' + quote(str(v))
            data += '&'
        return data.strip('&')

    @staticmethod
    def ParseFromData(desc, src):
        try:
            if not src:
                return
            if isinstance(src, str):
                src = json.loads(src)
            for k, v in src.items():
                setattr(desc, k, v)
        except Exception as es:
            Log.Error(es)

    @staticmethod
    def GetUrlHost(url):
        host = url.replace("https://", "")
        host = host.replace("http://", "")
        host = host.split("/")[0]
        host = host.split(":")[0]
        return host

    @staticmethod
    def GetDateStr(createdTime):
        timeArray = time.strptime(createdTime, "%Y-%m-%dT%H:%M:%S.%f%z")
        tick = int(time.mktime(timeArray) - time.timezone)
        now = int(time.time())
        day = int((int(now - time.timezone) / 86400) - (int(tick - time.timezone) / 86400))
        return time.localtime(tick), day

    @staticmethod
    def GetUpdateStr(createdTime):
        timeArray = time.strptime(createdTime, "%Y-%m-%dT%H:%M:%S.%f%z")
        now = int(time.time())
        tick = int(time.mktime(timeArray) - time.timezone)
        day = (now - tick) // (24 * 3600)
        hour = (now - tick) // 3600
        minute = (now - tick) // 60
        second = (now - tick)
        from tools.str import Str
        if day > 0:
            return "{}".format(day) + Str.GetStr(Str.DayAgo)
        elif hour > 0:
            return "{}".format(hour) + Str.GetStr(Str.HourAgo)
        elif minute > 0:
            return "{}".format(minute) + Str.GetStr(Str.MinuteAgo)
        else:
            return "{}".format(second) + Str.GetStr(Str.SecondAgo)

    @staticmethod
    def GetUpdateStrByTick(tick):
        now = int(time.time())
        day = (now - tick) // (24*3600)
        hour = (now - tick) // 3600
        minute = (now - tick) // 60
        second = (now - tick)

        from tools.str import Str
        if day > 0:
            return "{}".format(day) + Str.GetStr(Str.DayAgo)
        elif hour > 0:
            return "{}".format(hour) + Str.GetStr(Str.HourAgo)
        elif minute > 0:
            return "{}".format(minute) + Str.GetStr(Str.MinuteAgo)
        else:
            return "{}".format(second) + Str.GetStr(Str.SecondAgo)

    @staticmethod
    def GetDownloadSize(downloadLen):
        kb = downloadLen / 1024.0
        if kb <= 0.1:
            size = str(downloadLen) + "bytes"
        else:
            mb = kb / 1024.0
            if mb <= 0.1:
                size = str(round(kb, 2)) + "kb"
            else:
                size = str(round(mb, 2)) + "mb"
        return size


    @staticmethod
    def GetLookScaleModel(category, w, h, mat="jpg"):
        data = ToolUtil.GetModelByIndex(Setting.LookModelName.value, Setting.LookScale.value, mat)
        # 放大倍数不能过大，如果图片超过4k了，QImage无法显示出来，bug
        if min(w, h) > 3000:
            data["scale"] = 1
        elif min(w, h) > 2000:
            data["scale"] = 1.5
        return data

    @staticmethod
    def GetDownloadScaleModel(w, h, mat):
        dot = w * h
        # 条漫不放大
        if not config.CanWaifu2x:
            return {}
        return ToolUtil.GetModelByIndex(Setting.DownloadModelName.value, Setting.DownloadScale.value, mat)

    @staticmethod
    def GetAnimationFormat(data):
        # Android 的 Pillow 没有 webp 解码器，动图(webp/gif)识别会误判成静态，
        # 先让 Qt 读一次；不是动图就返回空串(与 PIL 语义一致)
        if platform_mobile.IsAndroid():
            size = ToolUtil.GetPictureSizeQt(data)
            if size:
                return size[2].upper() if size[3] else ""
        try:
            from PIL import Image
            from io import BytesIO
            a = BytesIO(data)
            img = Image.open(a)

            format = ""
            if getattr(img, "is_animated", ""):
                format = img.format
            a.close()
            return format
        except Exception as es:
            Log.Error(es)
        size = ToolUtil.GetPictureSizeQt(data)
        if size:
            return size[2].upper() if size[3] else ""
        return ""

    @staticmethod
    def GetPictureSizeQt(data):
        """ 用 Qt 自己的图像栈读尺寸/格式/是否动图；读不出来返回 None

        Android 的 Pillow 是 p4a 编的，只有 png/jpg/gif，没有 webp 解码器，
        而 JM 下发的图正是 webp：PIL 报 "cannot identify image file"，
        于是 mat 被兜底成 "jpg"、isAni 恒为 False。这里和看图界面用同一套解码器。
        """
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            from PySide6.QtGui import QImageReader
            ba = QByteArray(data)
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            try:
                reader = QImageReader(buf)
                reader.setDecideFormatFromContent(True)
                size = reader.size()
                if not size.isValid() or size.width() <= 0 or size.height() <= 0:
                    return None
                fmt = bytes(reader.format()).decode("utf-8", "ignore").lower()
                if fmt in ("jpeg", "jpg"):
                    mat = "jpg"
                elif fmt in ("png", "gif", "webp", "bmp"):
                    mat = fmt
                else:
                    mat = fmt or "jpg"
                # 必须是"能证明"的动图：imageCount() 拿不到(-1)时按静态处理，
                # 否则静态 webp 会被当成动图而跳过分割还原(那就又错位了)
                isAnima = False
                try:
                    isAnima = bool(reader.supportsAnimation()) and reader.imageCount() > 1
                except Exception:
                    isAnima = False
                return size.width(), size.height(), mat, isAnima
            finally:
                buf.close()
        except Exception as es:
            Log.Warn("GetPictureSizeQt failed:{}".format(es))
            return None

    @staticmethod
    def GetPictureSize(data):
        if not data:
            return 0, 0, "jpg", False
        # Android 上先问 Qt：Pillow 解不了 webp，直接走 PIL 只会刷一屏 traceback
        if platform_mobile.IsAndroid():
            size = ToolUtil.GetPictureSizeQt(data)
            if size:
                return size
        try:
            from PIL import Image
            from io import BytesIO
            a = BytesIO(data)
            img = Image.open(a)
            isAnima = getattr(img, "is_animated", False)
            if img.format == "PNG":
                mat = "png"
            elif img.format == "GIF":
                mat = "gif"
            elif img.format == "WEBP":
                mat = "webp"
            else:
                mat = "jpg"
            a.close()
            return img.width, img.height, mat, isAnima
        except Exception as es:
            Log.Error(es)
        # Pillow 不行就用 Qt 再读一次
        size = ToolUtil.GetPictureSizeQt(data)
        if size:
            return size
        return 0, 0, "jpg", False

    # @staticmethod
    # def GetLookModel(category):
    #     if Setting.LookModel.value == 0:
    #         if "Cosplay" in category or "cosplay" in category or "CosPlay" in category or "COSPLAY" in category:
    #             return 2
    #         return 3
    #     else:
    #         return Setting.LookModel.value

    # @staticmethod
    # def GetModelAndScale(model):
    #     if not model:
    #         return "cunet", 1, 1
    #     scale = model.get('scale', 0)
    #     noise = model.get('noise', 0)
    #     if index == 0:
    #         model = "anime_style_art_rgb"
    #     elif index == 1:
    #         model = "cunet"
    #     elif index == 2:
    #         model = "photo"
    #     else:
    #         model = "anime_style_art_rgb"
    #     return model, noise, scale

    @staticmethod
    def GetModelByIndex(modelName, scale, mat="jpg"):
        if not config.CanWaifu2x:
            return {}
        data = {"scale": scale}
        from sr_vulkan import sr_vulkan as sr
        data["model"] = getattr(sr, modelName, 0)
        data["model_name"] = modelName
        return data

    @staticmethod
    def GetShowModelName(name):
        if "WAIFU2X_CUNET" in name:
            return "Waifu2x(cunet)"
        elif "WAIFU2X_ANIME" in name:
            return "Waifu2x(anime)"
        elif "WAIFU2X_PHOTO" in name:
            return "Waifu2x(photo)"
        elif "REALCUGAN_PRO" in name:
            return "Realcugan(pro)"
        elif "REALCUGAN_SE" in name:
            return "Realcugan(se)"
        elif "REALSR" in name:
            return "RealSR"
        elif "REALESRGAN_X4PLUSANIME" in name:
            return "X4plusAnime"
        elif "REALESRGAN_X4PLUS" in name:
            return "X4Plus"
        elif "REALESRGAN_ANIMAVIDEOV3" in name:
            return "AnimaVideoV3"
        return name

    @staticmethod
    def GetCanSaveName(name):
        # 限制文件夹名称为255/3的长度
        return str(re.sub('[\\\/:*?"<>|\0\t\r\n]', '', name).rstrip(".").strip(" "))[:254//3-1].rstrip(".").strip(" ")

    @staticmethod
    def LoadCachePicture(filePath):
        try:
            c = CTime()
            formatList = [".jpg", ".png", ".gif", ".webp", ".bmp", ".apng"]
            for mat in formatList:
                if filePath[-4:] in formatList:
                    path = filePath
                elif filePath[-5:] in formatList:
                    path = filePath
                else:
                    path = filePath + mat
                if not os.path.isfile(path):
                    continue

                with open(path, "rb") as f:
                    data = f.read()
                    c.Refresh("LoadCache", path)
                    if len(data) < 20:
                        Log.Debug(f"load_fail_picture, {path}")
                        continue
                    return data

        except Exception as es:
            Log.Error(es)
        return None

    @staticmethod
    def SavePicture(data, path, format):
        if path and not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))

        formatList = [".jpg", ".png", ".gif", ".webp", ".bmp", ".apng", "jpeg"]
        if path and data:
            if path[-4:] in formatList:
                pass
            elif path[-5:] in formatList:
                pass
            else:
                path = path + "." + format
            with open(path, "wb+") as f:
                f.write(data)

    @staticmethod
    def IsHaveFile(filePath):
        try:
            if os.path.isfile(filePath):
                return True
            return False
        except Exception as es:
            Log.Error(es)
        return False

    @staticmethod
    def DiffDays(d1, d2):
        return (int(d1 - time.timezone) // 86400) - (int(d2 - time.timezone) // 86400)

    @staticmethod
    def GetCurZeroDatatime(tick):
        from datetime import timedelta
        from datetime import datetime
        now = datetime.fromtimestamp(tick)
        delta = timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
        zeroDatetime = now - delta
        return int(time.mktime(zeroDatetime.timetuple()))

    @staticmethod
    def GetTimeTickEx(strDatetime):
        if not strDatetime:
            return 0
        timeArray = time.strptime(strDatetime, "%Y-%m-%d %H:%M:%S")
        tick = int(time.mktime(timeArray))
        return tick

    @staticmethod
    def Escape(s):
        s = s.replace("&", "&amp;")
        s = s.replace("<", "&lt;")
        s = s.replace(">", "&gt;")
        s = s.replace('"', "&quot;")
        s = s.replace('\'', "&#x27;")
        s = s.replace('\n', '<br/>')
        s = s.replace('  ', '&nbsp;')
        s = s.replace(' ', '&emsp;')
        return s

    # @staticmethod
    # def ParseBookInfo(data, bookId):
    #     soup = BeautifulSoup(data, features="lxml")
    #     from tools.book import BookInfo
    #     book = BookInfo()
    #     book.baseInfo.bookId = bookId
    #     infos = soup.find_all("div", class_="p-t-5 p-b-5")
    #     for tag in infos:
    #         data = tag.text.replace("\n", "").strip()
    #         data = re.split('[:：]', data, maxsplit=1)
    #         if len(data) < 2:
    #             continue
    #         data[0] = data[0].strip()
    #         data[1] = data[1].strip()
    #         if ToolUtil.IsSameName(data[0], "叙述"):
    #             book.pageInfo.des = data[1]
    #         elif ToolUtil.IsSameName(data[0], "頁數"):
    #             book.pageInfo.pages = int(data[1])
    #         elif ToolUtil.IsSameName(data[0], "上架日期"):
    #             mo = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", data[1])
    #             book.pageInfo.createDate = mo.group()
    #         elif ToolUtil.IsSameName(data[0], "更新日期"):
    #             mo = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", data[1])
    #             book.pageInfo.updateDate = mo.group()
    #         # print(data[0], data[1])
    #     tag = soup.find("img", class_="lazy_img img-responsive")
    #     book.baseInfo.coverUrl = tag.attrs.get("src", "")
    #     tag = soup.find("div", itemprop="name")
    #     if tag:
    #         book.baseInfo.title = tag.h1.text
    #
    #     tag = soup.find("li", class_="p-t-5 p-b-5", id="")
    #     mo = re.search(r"\d+", tag.text)
    #     if mo:
    #         book.pageInfo.commentNum = int(mo.group())
    #
    #     isFavorite = False
    #     tag = soup.find("span", class_="col btn collect-btn btn-primary")
    #     if tag:
    #         isFavorite = True
    #
    #     infos = soup.find_all("div", class_="tag-block")
    #     for tag in infos:
    #         data = re.split('[:：]', tag.text.strip("\n"))
    #         if len(data) < 2:
    #             continue
    #         if ToolUtil.IsSameName(data[0], "作者"):
    #             book.baseInfo.authorList = data[1].strip().strip("\n").split("\n")
    #         elif ToolUtil.IsSameName(data[0], "标签"):
    #             book.baseInfo.tagList = data[1].strip().strip("\n").split("\n")
    #     epsTag = soup.find("ul", class_="btn-toolbar")
    #     from tools.book import BookEps
    #     if not epsTag:
    #         # 不分章节
    #         epsInfo = BookEps()
    #         epsInfo.title = "第一章"
    #         epsInfo.epsUrl = "/photo/{}".format(bookId)
    #         book.pageInfo.epsInfo[0] = epsInfo
    #     else:
    #         infos = epsTag.find_all("a")
    #         index = 0
    #         for tag in infos:
    #             epsUrl = tag.attrs.get("href")
    #             text = tag.li.text.strip("\n")
    #             epsText = text.split("\n")
    #             epsInfo = BookEps()
    #             epsInfo.epsUrl = epsUrl
    #             if len(epsText) == 3:
    #                 epsIndex = epsText[0]
    #                 epsTitle = epsText[1]
    #                 epsTime = epsText[2]
    #                 epsInfo.title = epsIndex
    #                 epsInfo.epsName = epsTitle
    #                 epsInfo.time = epsTime
    #
    #                 book.pageInfo.epsInfo[index] = epsInfo
    #                 index += 1
    #             elif len(epsText) == 4:
    #                 epsIndex = epsText[0]
    #                 epsTitle = epsText[1] + epsText[2]
    #                 epsTime = epsText[3]
    #                 epsInfo.title = epsIndex
    #                 epsInfo.epsName = epsTitle
    #                 epsInfo.time = epsTime
    #                 book.pageInfo.epsInfo[index] = epsInfo
    #                 index += 1
    #
    #     return isFavorite, book

    @staticmethod
    def ParseBookInfo(v):
        from tools.book import BookInfo
        b = BookInfo()
        b.baseInfo.id = v.get("id")
        b.baseInfo.author = v.get("author")
        b.baseInfo.title = v.get("name")
        b.baseInfo.coverUrl = "/media/albums/{}_3x4.jpg".format(b.baseInfo.id)
        if isinstance(v.get("update_at"), int):
            b.baseInfo.addTime = v.get("update_at")
        if isinstance(v.get('update_at'), str) and v.get('update_at').isdigit():
            b.baseInfo.addTime = int(v.get("update_at"))
        category = v.get("category", {}).get("title")
        if category:
            b.baseInfo.category.append(category)
        category = v.get("category_sub", {}).get("title")
        if category:
            b.baseInfo.category.append(category)
        return b

    @staticmethod
    def ParseBookList(rawList):
        data = []
        for v in rawList:
            data.append(ToolUtil.ParseBookInfo(v))
        return data

    # 解析首页结果
    @staticmethod
    def ParseIndex2(result):
        parseData = []
        raw = json.loads(result)
        for v in raw:
            from tools.book import IndexInfo
            info = IndexInfo()
            bookList = ToolUtil.ParseBookList(v.get("content", []))
            info.title = v.get("title", "")
            info.id = v.get("id", "")
            info.slug = v.get("slug", "")
            info.type = v.get("type", "")
            info.bookList = bookList
            info.filter_val = v.get("filter_val", "")
            parseData.append(info)
        return parseData

    # 解析最近更新
    @staticmethod
    def ParseLatest2(result):
        raw = json.loads(result)
        bookList = ToolUtil.ParseBookList(raw)
        return bookList

    @staticmethod
    def ParseFavoritesReq2(result):
        bookList = []
        from tools.book import FavoriteInfo
        f = FavoriteInfo()
        raw = json.loads(result)
        f.total = int(raw.get("total"))
        f.count = int(raw.get("count"))
        f.bookList = ToolUtil.ParseBookList(raw.get("list", []))
        folderDict = {}
        f.fold = folderDict
        for v in raw.get("folder_list", []):
            folderDict[v.get("name")] = v.get("FID")
        return f

    @staticmethod
    def ParseMsgReq2(result):
        raw = json.loads(result)
        status = raw.get("status")
        msg = raw.get("msg")
        if status == "ok":
            return Status.Ok, msg
        return Status.Error, msg

    @staticmethod
    def ParseLogin2(result):
        raw = json.loads(result)
        from tools.user import User
        u = User()
        u.uid = raw.get("uid")
        u.userName = raw.get("username")
        u.title = raw.get("level_name")
        u.level = raw.get("level")
        u.coin = raw.get("coin")
        u.gender = raw.get("gender")
        u.favorites = raw.get('album_favorites')
        u.canFavorites = raw.get('album_favorites_max')
        u.exp = raw.get('exp', 0)
        u.nex_exp = raw.get('nextLevelExp', 0)
        u.jwttoken = raw.get('jwttoken')
        return u

    # 解析搜索结果
    @staticmethod
    def ParseSearch2(result):
        raw = json.loads(result)
        total = int(raw.get("total"))
        bookList = ToolUtil.ParseBookList(raw.get("content", []))
        return total, bookList

    # 解析搜索结果
    @staticmethod
    def ParseRecommend2(result):
        raw = json.loads(result)
        # total = int(raw.get("total"))
        bookList = ToolUtil.ParseBookList(raw.get("content", []))
        return len(bookList), bookList

    # 解析搜索结果
    @staticmethod
    def ParseCategory2(result):
        raw = json.loads(result)
        categoryList = []
        for v in raw.get("categories", []):
            from tools.book import Category
            b = Category()
            categoryId = v.get("id")
            b.id = categoryId
            b.name = v.get("name")
            b.slug = v.get("slug")
            b.type = v.get("type")
            b.total = v.get("total_albums")
            for v2 in v.get("sub_categories", []):
                b2 = Category()
                b2.id = v2.get("CID")
                b2.name = v2.get("name")
                b2.slug = v2.get("slug")
                b.sub_categories.append(b2)
            categoryList.append(b)
        categoryTitle = OrderedDict()
        for v in raw.get("blocks", []):
            categoryTitle[v.get("title")] = v.get("content")
        return categoryList, categoryTitle

    # 解析搜索结果
    @staticmethod
    def ParseSearchCategory2(result):
        raw = json.loads(result)
        total = int(raw.get("total"))
        bookList = ToolUtil.ParseBookList(raw.get("content", []))
        return total, bookList

    @staticmethod
    def ParseBookInfo2(result):
        raw = json.loads(result)
        from tools.book import BookInfo
        b = BookInfo()
        bookId = raw["id"]
        b.baseInfo.coverUrl = "/media/albums/{}_3x4.jpg".format(bookId)
        b.baseInfo.bookId = bookId
        if raw.get('series_id') and raw.get('series_id') != "0":
            b.baseInfo.series_id = raw.get('series_id')
        b.baseInfo.title = raw.get('name')
        b.baseInfo.likes = raw.get('likes')
        b.baseInfo.views = raw.get('total_views')
        addTime = raw.get("addtime", "")
        if isinstance(addTime, str) and addTime.isdigit():
            b.baseInfo.addTime = int(addTime)

        if raw.get('price'):
            b.baseInfo.price = raw.get('price', 0)
        if raw.get('purchased'):
            b.baseInfo.purchased = raw.get('purchased', True)
        b.baseInfo.authorList = raw.get("author")
        b.baseInfo.tagList = raw.get("tags", [])
        b.baseInfo.workList = raw.get("works", [])
        b.baseInfo.actorList = raw.get("actors", [])
        b.pageInfo.des = raw.get("description")
        b.pageInfo.commentNum = int(raw.get("comment_total"))
        isFavorite = raw.get("is_favorite")

        from tools.book import BookEps
        ## 264793不按sort顺序
        series = raw.get("series", [])
        if series:
            for index, v in enumerate(series):
                epsInfo = BookEps()
                epsInfo.index = index
                epsInfo.sort = int(v.get("sort"))
                from tools.str import Str
                if v.get("name"):
                    epsInfo.title = Str.GetStr(Str.EpisodeTitleWithName).format(epsInfo.index+1, v.get("name"))
                else:
                    epsInfo.title = Str.GetStr(Str.EpisodeTitle).format(epsInfo.index+1)
                epsInfo.epsId = v.get('id')
                epsInfo.epsName = v.get("name")
                b.pageInfo.epsInfo[epsInfo.index] = epsInfo
        else:
            from tools.str import Str
            epsInfo = BookEps()
            epsInfo.title = Str.GetStr(Str.EpisodeTitle).format(1)
            epsInfo.epsUrl = "/photo/{}".format(bookId)
            epsInfo.epsId = bookId
            b.pageInfo.epsInfo[0] = epsInfo
        return b, isFavorite

    @staticmethod
    def ParseBookEpsScramble(data):
        try:
            mo = re.search(r"(?<=var scramble_id = )\w+", data)
            return int(mo.group())
        except Exception as es:
            Log.Error(es)
            return 220980

    @staticmethod
    def ParseBookEpsInfo2(result):
        raw = json.loads(result)
        from tools.book import BookEps
        epsInfo = BookEps()
        epsInfo.epsId = raw.get("id")
        epsInfo.aid = raw.get("series_id")
        epsInfo.epsName = raw.get("name")
        for info in raw.get("series", []):
            if str(info.get("id")) == str(epsInfo.epsId):
                epsInfo.sort = int(info.get("sort"))
        allIds = []
        idMap = {}
        for name in raw.get("images", []):
            mo = re.search(r"\d+", name)
            if not mo:
                continue
            picId = mo.group()
            allIds.append(int(picId) -1)
        for index, picId in enumerate(sorted(allIds)):
                idMap[picId] = index
        for name in raw.get("images", []):
            mo = re.search(r"\d+", name)
            if not mo:
                continue
            picId = mo.group()
            index = idMap.get(int(picId)-1)
            epsInfo.pictureName[index] = name.split(".")[0]
            epsInfo.pictureUrl[index] = "/media/photos/{}/{}".format(epsInfo.epsId, name)
        epsInfo.allIndex = sorted(epsInfo.pictureUrl.keys())
        return epsInfo

    # 解析搜索结果
    @staticmethod
    def ParseReadBook2(result):
        raw = json.loads(result)
        from tools.book import BookEps
        epsInfo = BookEps()
        epsInfo.epsId = raw.get("id")
        epsInfo.series_id = raw.get("series_id")
        epsInfo.epsName = raw.get("name")
        # for info in raw.get("series", []):
        #     if str(info.get("id")) == str(epsInfo.epsId):
        #         epsInfo.sort = int(info.get("sort"))
        allIds = []
        idMap = {}
        for v in raw.get("images", []):
            page = v.get("page")
            image = v.get("image")
            allIds.append((page, image))

        # for index, picId in enumerate(sorted(allIds)):
        #     idMap[picId] = index
        for index, v in enumerate(sorted(allIds, key=lambda a:a[0])):
            _, image = v
            mo = re.search(r"(?<=media/photos/{}/).*\?".format(epsInfo.epsId), image)
            name = mo.group().strip("?")
            epsInfo.pictureName[index] = name.split(".")[0]
            epsInfo.pictureUrl[index] = "/media/photos/{}/{}".format(epsInfo.epsId, name)
        epsInfo.allIndex = sorted(epsInfo.pictureUrl.keys())
        epsInfo.scrambleId = raw.get("scramble_id", "")
        return epsInfo

    @staticmethod
    def ParseBookComment(result):
        raw = json.loads(result)
        from tools.book import CommentInfo
        commentList = []
        total = int(raw.get("total", 0))
        for v in raw.get("list", []):
            b = CommentInfo()
            b.id = v.get("CID")
            b.uid = v.get("UID")
            b.title = v.get("expinfo", {}).get("level_name")
            b.level = v.get("expinfo", {}).get("level")
            b.name = v.get("username")
            photo = v.get("photo")
            if photo != "nopic-Male.gif" and photo != "nopic-Female.gif":
                b.headUrl = "/media/users/" + photo
            b.content = v.get("content")
            b.like = v.get("likes")
            b.date = v.get("addtime")
            b.linkBookName = v.get("name")
            b.linkBookId = v.get("AID")
            for v2 in v.get("replys", []):
                b2 = CommentInfo()
                b2.id = v2.get("CID")
                b2.uid = v2.get("UID")
                b2.title = v2.get("expinfo", {}).get("level_name")
                b2.level = v2.get("expinfo", {}).get("level")
                b2.name = v2.get("username")
                photo = v2.get("photo")
                if photo != "nopic-Male.gif" and photo != "nopic-Female.gif":
                    b2.headUrl = "/media/users/" + photo
                b2.content = v2.get("content")
                b2.like = v2.get("likes")
                b2.date = v2.get("addtime")
                b.linkBookName = v2.get("name")
                b.linkBookId = v2.get("AID")
                b.subComments.append(b2)
            commentList.append(b)
        return commentList, total

    @staticmethod
    def ParseSendBookComment(result):
        raw = json.loads(result)
        return raw.get("msg", "")

    @staticmethod
    def MergeUrlParams(url, data: dict):
        if not data:
            return url
        if url[-1] != "/":
            url += "/?"
        for key, value in data.items():
            url += "{}={}".format(key, value)
            url += "&"
        return url.strip("&")

    # 解析登录结果
    @staticmethod
    def ParseMsg(data):
        isSuc = False
        msg = ""
        errList = re.findall(r"(?<=toastr\[\'error\'\]\(\").*\"", data)
        if errList:
            msg = "\n".join(errList)

        mo = re.search(r"(?<=toastr\[\'success\'\]\(\").*\"", data)
        if mo:
            isSuc = True
            msg = mo.group().strip("\"")
        return isSuc, msg

    @staticmethod
    def ParseHistoryReq2(result):
        raw = json.loads(result)
        bookList = ToolUtil.ParseBookList(raw.get("list", []))
        total = int(raw.get("total", 0))
        return bookList, total

    @staticmethod
    def ParseSerializationReq2(result):
        raw = json.loads(result)
        bookList = ToolUtil.ParseBookList(raw.get("list", []))
        total = int(raw.get("total", 0))
        return bookList, total

    @staticmethod
    def ParseRandomRecommendReq2(result):
        raw = json.loads(result)
        bookList = ToolUtil.ParseBookList(raw)
        return bookList, len(bookList)

    # 解析用户信息
    # @staticmethod
    # def ParseUserInfo(data):
    #     from tools.user import User
    #     user = User()
    #     user.isLogin = True
    #     soup = BeautifulSoup(data, features="lxml")
    #     tag = soup.find("img", class_="header-personal-avatar")
    #     user.imgUrl = tag.attrs.get("src", "")
    #     tag = soup.find("div", class_="header-right-username")
    #     user.userName = tag.text
    #
    #     infos = soup.find_all("div", class_="header-profile-row")
    #     userAttr = {}
    #     for tag in infos:
    #         pass
    #         nameTag = tag.find("div", class_="header-profile-row-name")
    #         nameValue = tag.find("div", class_="header-profile-row-value")
    #         if nameTag and nameValue:
    #             name = nameTag.text.replace(" ", "").replace("\n", "")
    #             value = nameValue.text.replace(" ", "").replace(
    #                 "\n", "")
    #             userAttr[name] = value
    #     user.userAttr = userAttr
    #     return user

    # 解析收藏
    # @staticmethod
    # def ParseFavorite(data):
    #     soup = BeautifulSoup(data, features="lxml")
    #     tag = soup.find("div", class_="pull-left m-l-20")
    #     text = tag.text.replace("\n", "").replace(" ", "")
    #     data = re.findall(r"\d+", text)
    #     curNum = int(data[0])
    #     maxNum = int(data[1])
    #     tags = soup.find_all("div", class_="thumb-overlay")
    #     books = []
    #     for tag in tags:
    #         from tools.book import BookInfo
    #         info = BookInfo()
    #         info.baseInfo.bookUrl = tag.parent.attrs.get("href")
    #         if not info.baseInfo.bookUrl:
    #             continue
    #         info.baseInfo.bookId = re.search(r"(?<=/album/)\w*", info.baseInfo.bookUrl).group()
    #         info.baseInfo.coverUrl = tag.img.attrs.get("src", "")
    #         if info.baseInfo.coverUrl and "http" not in info.baseInfo.coverUrl:
    #             info.baseInfo.coverUrl = GlobalConfig.Url.value + info.baseInfo.coverUrl
    #         info.baseInfo.title = tag.img.attrs.get("title")
    #         for tag2 in tag.find_next_siblings():
    #             className = " ".join(tag2.attrs.get('class', []))
    #             if className == "video-title title-truncate":
    #                 info.baseInfo.title = tag2.text.replace("\n", "").strip()
    #                 pass
    #         books.append(info)
    #     return curNum, maxNum, books

    # 解析首页结果
    # @staticmethod
    # def ParseIndex(data):
    #     soup = BeautifulSoup(data, features="lxml")
    #     tags = soup.find_all("div", class_="thumb-overlay-albums")
    #     from tools.book import BookInfo
    #     books = []
    #     for tag in tags:
    #         info = BookInfo()
    #         info.baseInfo.bookUrl = tag.parent.attrs.get("href")
    #         info.baseInfo.bookId = re.search("(?<=/album/)\w*", info.baseInfo.bookUrl).group()
    #         info.baseInfo.coverUrl = tag.img.attrs.get("data-src")
    #         info.baseInfo.title = tag.img.attrs.get("title")
    #         for tag2 in tag.parent.find_next_siblings():
    #             className = " ".join(tag2.attrs.get('class', []))
    #             if className == "title-truncate hidden-xs":
    #                 info.baseInfo.author = tag2.a.text.replace("\n", "").strip()
    #             elif className == "title-truncate tags":
    #                 info.baseInfo.tagStr = tag2.text.replace("標籤: ", "").replace("\n", "").strip()
    #             elif className == "video-views pull-left hidden-xs":
    #                 info.baseInfo.date = tag2.text.replace("\n", "").strip()
    #         books.append(info)
    #     return books

    # 解析评论
    # @staticmethod
    # def ParseComment(data):
    #     soup = BeautifulSoup(data, features="lxml")
    #
    #     allComment = []
    #     ToolUtil.ParseCommentData(soup, allComment)
    #     return allComment

    # @staticmethod
    # def ParseCommentData(tag, allComment, isSubComment=False):
    #     from tools.book import CommentInfo
    #     tags = tag.find_all("div", class_="timeline")
    #     for tag in tags:
    #         info = CommentInfo()
    #         index = tag.attrs.get("data-cid")
    #         if not index:
    #             continue
    #         if not isSubComment and "{" in index:
    #             continue
    #         info.id = index
    #         userTag = tag.find("div", class_="timeline-left")
    #         info.headUrl = userTag.a.img.attrs.get("src", "")
    #         info.level = userTag.div.text.strip("\n ")
    #
    #         rightTag = tag.find("div", class_="timeline-right")
    #         nameTag = rightTag.find("span", class_="timeline-username")
    #         info.name = nameTag.text.strip("\n ")
    #
    #         titleTag = rightTag.find("div", class_="timeline-user-title")
    #         info.title = titleTag.text.strip("\n ")
    #
    #         commentTag = rightTag.find("div", class_="timeline-content")
    #         info.content = commentTag.text.strip("\n ")
    #
    #         timeTag = rightTag.find("div", class_="timeline-date")
    #         info.date = timeTag.text.strip("\n ")
    #
    #         commentLinkTag = rightTag.find("div", class_="timeline-ft")
    #         if commentLinkTag:
    #             linkBookUrl = commentLinkTag.a.attrs.get("href").replace("\\/", "/")
    #             info.linkBookId = re.search(r"(?<=/album/)\w*", linkBookUrl).group()
    #             info.linkBookName = linkBookUrl.replace("/album/{}/".format(info.linkBookId), "").strip("\n ")
    #         allComment.append(info)
    #         otherTag = tag.find("div", class_="other-timelines")
    #         if otherTag:
    #             ToolUtil.ParseCommentData(otherTag, info.subComments, True)

    # 解析搜索结果
    # @staticmethod
    # def ParseSearch(data):
    #     soup = BeautifulSoup(data, features="lxml")
    #     tags = soup.find_all("div", class_="thumb-overlay")
    #     from tools.book import BookInfo
    #     books = []
    #     for tag in tags:
    #         info = BookInfo()
    #         info.baseInfo.bookUrl = tag.parent.attrs.get("href")
    #         info.baseInfo.bookId = re.search(r"(?<=/album/)\w*", info.baseInfo.bookUrl).group()
    #         info.baseInfo.coverUrl = tag.img.attrs.get("data-original")
    #         info.baseInfo.title = tag.img.attrs.get("title")
    #         for tag2 in tag.parent.find_next_siblings():
    #             className = " ".join(tag2.attrs.get('class', []))
    #             if className == "title-truncate hidden-xs":
    #                 info.baseInfo.author = tag2.a.text.replace("\n", "").strip()
    #             elif className == "title-truncate tags":
    #                 info.baseInfo.tagStr = tag2.text.replace("標籤: ", "").replace("\n", "").strip()
    #             elif className == "video-views pull-left hidden-xs":
    #                 info.baseInfo.date = tag2.text.replace("\n", "").strip()
    #         books.append(info)
    #     maxPage = 1
    #
    #     pageTag = soup.find("ul", class_="pagination pagination-lg")
    #     if pageTag:
    #         allPage = pageTag.find_all("option")
    #         for v in allPage:
    #             maxPage = max(maxPage, int(v.text))
    #     return maxPage, books

    # 解析图片Url地址
    # @staticmethod
    # def ParsePictureUrl(data):
    #     soup = BeautifulSoup(data, features="lxml")
    #     infos = soup.find_all("div", id=re.compile(r"page_\d+"))
    #     # infos = soup.find_all("div")
    #     mo = re.search(r"(?<=var scramble_id = )\w+", data)
    #     minAid = int(mo.group())
    #     mo = re.search(r"(?<=var aid = )\w+", data)
    #     aid = int(mo.group())
    #     pictureUrl = {}
    #     pictureName = {}
    #     for tag in infos:
    #         tag2 = tag.find_next_sibling()
    #         url = tag2.get("data-original")
    #         id = re.search(r"\d+", tag2.get("id")).group()
    #         pictureName[int(id)-1] = id
    #         pictureUrl[int(id)-1] = url
    #     return aid, minAid, pictureUrl, pictureName

    # ---- 图片分割(分块还原)的 Qt 实现 ----
    # 官方算法(见 jmcomic JmImageTool.decode_and_save)：把高 h 按 num 等分，
    # 余数 rem 归"最下面那一块"，然后从最下面那块开始往上依次贴回(最后贴最上面那块)。
    # 注意：只有 h % num == 0 时这个变换才是对合(involution)，一般情况下
    # 同一张图被还原两次 = 彻底错位，所以任何路径都只能对原始字节做一次。

    @staticmethod
    def LoadQImage(imgData):
        """ bytes -> QImage(无效返回 isNull 的 QImage) """
        from PySide6.QtGui import QImage
        q = QImage()
        if imgData:
            try:
                q.loadFromData(imgData)
            except Exception as es:
                Log.Warn("LoadQImage failed:{}".format(es))
        return q

    @staticmethod
    def SegmentQImage(img, num):
        """ 用 QImage 做分块还原；img 无效/num 不合理时原样返回 """
        try:
            if img is None or num <= 1:
                return img
            from PySide6.QtCore import QRect
            from PySide6.QtGui import QImage, QPainter
            w = img.width()
            h = img.height()
            if w <= 0 or h <= 0:
                return img
            c = h // num
            if c <= 0:
                return img
            rem = h % num
            out = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            if out.isNull():
                return img
            out.fill(0)
            painter = QPainter(out)
            try:
                yDst = 0
                for i in range(num):
                    move = c + (rem if i == 0 else 0)
                    ySrc = h - c * (i + 1) - rem
                    if ySrc < 0 or yDst + move > h or ySrc + move > h:
                        continue
                    painter.drawImage(QRect(0, yDst, w, move), img, QRect(0, ySrc, w, move))
                    yDst += move
            finally:
                painter.end()
            return out
        except Exception as es:
            Log.Error("SegmentQImage failed, num:{} err:{}".format(num, es))
            return img

    @staticmethod
    def SegmentationQImage(imgData, epsId, scramble_id, pictureName):
        """ bytes -> QImage|None：Qt 解码 + 分块还原

        看图线程直接用这个(拿到就是能显示的 QImage)，省掉"还原→编码→再解码"的来回。
        解码不了返回 None，调用方自行决定要不要退回原始字节。
        """
        try:
            q = ToolUtil.LoadQImage(imgData)
            if q.isNull():
                return None
            num = ToolUtil.GetSegmentationNum(epsId, scramble_id, pictureName)
            if num > 1:
                q = ToolUtil.SegmentQImage(q, num)
            return q
        except Exception as es:
            Log.Error("SegmentationQImage failed:{}".format(es))
            return None

    @staticmethod
    def ImageFormatFromData(data):
        """ 从字节头判断图片格式(Qt 保存时用它保持原扩展名) """
        try:
            head = bytes(data[:16])
        except Exception:
            return ""
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return "PNG"
        if head[:3] == b"\xff\xd8\xff":
            return "JPEG"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "WEBP"
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return "GIF"
        if head[:2] == b"BM":
            return "BMP"
        return ""

    @staticmethod
    def _SaveQImage(img, path, toFormat=""):
        """ QImage -> 文件；返回实际写入的格式或空串 """
        formats = []
        if toFormat:
            formats.append(str(toFormat).upper().replace("JPG", "JPEG"))
        for fmt in ("PNG", "JPEG"):
            if fmt not in formats:
                formats.append(fmt)
        for fmt in formats:
            try:
                quality = 95 if fmt in ("JPEG", "WEBP") else -1
                if img.save(path, fmt, quality):
                    return fmt
            except Exception as es:
                Log.Warn("save qimage as {} failed:{}".format(fmt, es))
        return ""

    @staticmethod
    def _SaveQImageToBytes(img, toFormat=""):
        """ QImage -> bytes；返回 (bytes, 格式) 或 (None, "") """
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        formats = []
        if toFormat:
            formats.append(str(toFormat).upper().replace("JPG", "JPEG"))
        for fmt in ("PNG", "JPEG"):
            if fmt not in formats:
                formats.append(fmt)
        for fmt in formats:
            try:
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                try:
                    # 有损格式给 95：旧路径(PIL 默认 80)在这里会掉画质
                    ok = img.save(buf, fmt, 95 if fmt in ("JPEG", "WEBP") else -1)
                finally:
                    buf.close()
                if ok and not ba.isEmpty():
                    return bytes(ba), fmt
            except Exception as es:
                Log.Warn("encode qimage as {} failed:{}".format(fmt, es))
        return None, ""

    @staticmethod
    def SegmentationPictureQt(imgData, epsId, scramble_id, pictureName, toFormat=""):
        """ Qt 版 SegmentationPicture：解码 + 还原 + 编码；失败返回 None

        Android 的 Pillow 是 p4a 编出来的，只有 png/jpg/gif，**没有 webp 解码器**
        (包里只有 PIL/_webp.pyi，没有 _webp.so)，而 JM 下发的图正是 webp；
        这时 PIL 会抛 "cannot identify image file"，必须靠 Qt 自己的图像栈
        (看图界面显示用的就是它，能解 webp)。
        """
        try:
            q = ToolUtil.SegmentationQImage(imgData, epsId, scramble_id, pictureName)
            if q is None or q.isNull():
                return None
            fmt = toFormat or ToolUtil.ImageFormatFromData(imgData)
            value, used = ToolUtil._SaveQImageToBytes(q, fmt)
            return value
        except Exception as es:
            Log.Error("SegmentationPictureQt failed:{}".format(es))
            return None

    @staticmethod
    def SegmentationPictureToDiskQt(imgData, epsId, scramble_id, pictureName, path, toFormat=""):
        """ Qt 版 SegmentationPictureToDisk：解码 + 还原 + 落盘；失败返回 False """
        try:
            q = ToolUtil.SegmentationQImage(imgData, epsId, scramble_id, pictureName)
            if q is None or q.isNull():
                return False
            fmt = toFormat or ToolUtil.ImageFormatFromData(imgData)
            return bool(ToolUtil._SaveQImage(q, path, fmt))
        except Exception as es:
            Log.Error("SegmentationPictureToDiskQt failed:{}".format(es))
            return False

    # 获得图片分割数
    @staticmethod
    def GetSegmentationNum(epsId, scramble_id, pictureName):
        # 这个函数绝不能抛异常：scramble_id 来自接口/缓存，可能是 ""/None/非数字，
        # 一旦抛出去，上层(TaskMulti → 看图)就把这张图当成"解密失败"丢掉了。
        try:
            scramble_id = int(scramble_id or 0)
        except (TypeError, ValueError):
            scramble_id = 0
        try:
            epsId = int(epsId or 0)
        except (TypeError, ValueError):
            epsId = 0
        if pictureName is None:
            pictureName = ""
        else:
            pictureName = str(pictureName)
        if epsId < scramble_id:
            num = 0
        elif epsId < 268850:
            num = 10
        elif epsId > 421926:
            string = str(epsId) + pictureName
            string = string.encode()
            string = hashlib.md5(string).hexdigest()
            num = ord(string[-1])
            num %= 8
            num = num * 2 + 2
        else:
            string = str(epsId) + pictureName
            string = string.encode()
            string = hashlib.md5(string).hexdigest()
            num = ord(string[-1])
            num %= 10
            num = num * 2 + 2
        return num

    # 图片分割合成
    @staticmethod
    def SegmentationPicture(imgData, epsId, scramble_id, bookId):
        num = ToolUtil.GetSegmentationNum(epsId, scramble_id, bookId)
        if num <= 1 or not imgData:
            return imgData

        # Android 上优先用 Qt：p4a 编出来的 Pillow 没有 webp 解码器，JM 下发的图
        # 又偏偏是 webp，PIL 会抛 "cannot identify image file"，以前这里兜底返回原图，
        # 真机上看到的就是"图片分割异常、图像错位"。
        if platform_mobile.IsAndroid():
            qt = ToolUtil.SegmentationPictureQt(imgData, epsId, scramble_id, bookId)
            if qt:
                return qt

        try:
            from PIL import Image
            from io import BytesIO
            src = BytesIO(imgData)
            srcImg = Image.open(src)
            try:
                size = (width, height) = srcImg.size
                desImg = Image.new(srcImg.mode, size)
                # srcImg.format 可能是 None(jpg 里没有 format 就会保存失败)，
                # 那种情况由下面的 except 兜住
                format = srcImg.format

                rem = height % num
                copyHeight = math.floor(height / num)
                block = []
                totalH = 0
                for i in range(num):
                    h = copyHeight * (i + 1)
                    if i == num - 1:
                        h += rem
                    block.append((totalH, h))
                    totalH = h

                h = 0
                for start, end in reversed(block):
                    coH = end - start
                    temp_img = srcImg.crop((0, start, width, end))
                    desImg.paste(temp_img, (0, h, width, h + coH))
                    h += coH

                des = BytesIO()
                desImg.save(des, format)
                value = des.getvalue()
                desImg.close()
                des.close()
                return value
            finally:
                try:
                    srcImg.close()
                    src.close()
                except Exception:
                    pass
        except Exception as es:
            # 失败必须把输入原样返回：返回 None 会被 consumer 塞进结果队列，
            # 看图界面拿到后把 info.data 覆盖成 None，整页图直接消失。
            Log.Error("SegmentationPicture failed, epsId:{} scrambleId:{} len:{} err:{}".format(
                epsId, scramble_id, len(imgData) if imgData else 0, es))
            # Pillow 不行(缺 codec/格式特殊)就换 Qt 的图像栈再试一次
            qt = ToolUtil.SegmentationPictureQt(imgData, epsId, scramble_id, bookId)
            if qt:
                Log.Warn("SegmentationPicture: 已用 Qt 图像栈还原(epsId:{} scrambleId:{})".format(
                    epsId, scramble_id))
                return qt
            return imgData

    # 图片分割合成
    @staticmethod
    def SegmentationPictureToDisk(imgData, epsId, scramble_id, bookId, path, toFormat):
        num = ToolUtil.GetSegmentationNum(epsId, scramble_id, bookId)

        # 同 SegmentationPicture：Android 的 Pillow 解不了 webp(也没法转 png)，
        # 先用 Qt 走一遍；否则"保存到手机"存下来的会是被打乱的原图。
        if platform_mobile.IsAndroid():
            if ToolUtil.SegmentationPictureToDiskQt(imgData, epsId, scramble_id, bookId, path, toFormat):
                return True

        try:
            from PIL import Image
            from io import BytesIO
            src = BytesIO(imgData)
            srcImg = Image.open(src)
            try:
                if num <= 1:
                    srcImg.save(path, toFormat)
                    return True

                size = (width, height) = srcImg.size
                desImg = Image.new(srcImg.mode, size)
                format = srcImg.format

                rem = height % num
                copyHeight = math.floor(height / num)
                block = []
                totalH = 0
                for i in range(num):
                    h = copyHeight * (i + 1)
                    if i == num - 1:
                        h += rem
                    block.append((totalH, h))
                    totalH = h

                h = 0
                for start, end in reversed(block):
                    coH = end - start
                    temp_img = srcImg.crop((0, start, width, end))
                    desImg.paste(temp_img, (0, h, width, h + coH))
                    h += coH

                desImg.save(path, toFormat)
                return True
            finally:
                try:
                    srcImg.close()
                    src.close()
                except Exception:
                    pass
        except Exception as es:
            Log.Error("SegmentationPictureToDisk failed, epsId:{} scrambleId:{} path:{} len:{} err:{}".format(
                epsId, scramble_id, path, len(imgData) if imgData else 0, es))
            # Pillow 不行就换 Qt 再试一次(桌面端遇到 Pillow 不支持的格式时同理)
            if ToolUtil.SegmentationPictureToDiskQt(imgData, epsId, scramble_id, bookId, path, toFormat):
                Log.Warn("SegmentationPictureToDisk: 已用 Qt 图像栈还原(epsId:{})".format(epsId))
                return True
            # 分割失败也要把原始字节落盘：至少让这一页能显示出来(返回 False = 没做分割)
            try:
                with open(path, "wb") as f:
                    f.write(imgData)
            except Exception as es2:
                Log.Error("SegmentationPictureToDisk write raw failed, path:{} err:{}".format(path, es2))
            return False

    @staticmethod
    def IsSameName(name1, name2):
        return Converter('zh-hans').convert(name1) == Converter('zh-hans').convert(name2)


    @staticmethod
    def GetPictureFormat(data):
        import imghdr
        mat = imghdr.what(None, data)
        if mat:
            return mat
        return "jpg"

    @staticmethod
    def GetStrMaxLen(str, maxLen=6):
        if len(str) > maxLen:
            return str[:maxLen] + "..."
        else:
            return str

    @staticmethod
    def GetRealUrl(url, path):
        if path:
            return url + "/static/" + path
        else:
            return url

    @staticmethod
    def GetRealPath(path, direction):
        if path:
            data = "{}/{}".format(direction, path)
            return data
        else:
            return path

    @staticmethod
    def GetMd5RealPath(path, direction):
        if path:
            a = hashlib.md5(path.encode("utf-8")).hexdigest()
            return "{}/{}.jpg".format(direction, a)
        else:
            return path

    @staticmethod
    def SaveFile(data, filePath):
        if not data:
            return
        if not filePath:
            return

        try:
            fileDir = os.path.dirname(filePath)

            if not os.path.isdir(fileDir):
                os.makedirs(fileDir)

            with open(filePath, "wb+") as f:
                f.write(data)

            Log.Debug("add chat cache, cachePath:{}".format(filePath))

        except Exception as es:
            Log.Error(es)

    @staticmethod
    def GetComicInfoXml(epsId, picNum, bookInfo):
        from lxml import etree
        from tools.book import BookInfo
        assert isinstance(bookInfo, BookInfo)
        root = etree.Element("ComicInfo")

        title = etree.SubElement(root, "Title")  # 标题
        title.text = bookInfo.baseInfo.title

        publish = etree.SubElement(root, "Publisher")  # 标题
        publish.text = config.ProjectName

        writer = etree.SubElement(root, "Writer")  # 作者
        writer.text = bookInfo.baseInfo.author
        if bookInfo.baseInfo.authorList:
            writer.text = bookInfo.baseInfo.authorList[0]

        desc = etree.SubElement(root, "Summary")  # 摘要
        desc.text = bookInfo.pageInfo.des

        bookId = etree.SubElement(root, "BookId")  # 当前章节
        bookId.text = str(bookInfo.baseInfo.id)

        series = etree.SubElement(root, "Series")  # 当前章节
        series.text = str(bookInfo.baseInfo.title)

        number = etree.SubElement(root, "Number")  # 当前章节
        number.text = str(epsId+1)

        count = etree.SubElement(root, "Count")  # 总章节
        count.text = str(bookInfo.pageInfo.maxEps() + 1)

        genre = etree.SubElement(root, "Genre")  # 分类
        genre.text = ",".join(bookInfo.baseInfo.category)

        tags = etree.SubElement(root, "Tags")
        tags.text = ",".join(bookInfo.baseInfo.tagList)

        everyoneTags = ["无h", "無h"]
        isNotH = ToolUtil.IsHaveAssignTag(tags, everyoneTags)
        ageRating = etree.SubElement(root, "AgeRating")  # R18+  Everyone
        if isNotH:
            ageRating.text = "Everyone"
        else:
            ageRating.text = "R18+"

        pageCount = etree.SubElement(root, "PageCount")  # ue
        pageCount.text = str(picNum)

        blackAndWhite = etree.SubElement(root, "BlackAndWhite")  # Yes No
        everyoneTags = ["全彩", "cosplay"]
        isColor = ToolUtil.IsHaveAssignTag(tags.text, everyoneTags)
        if isColor:
            blackAndWhite.text = "No"
        else:
            blackAndWhite.text = "Yes"

        manga = etree.SubElement(root, "Manga")  # Yes No
        everyoneTags = ["cosplay"]
        isCos = ToolUtil.IsHaveAssignTag(tags.text, everyoneTags)
        if isCos:
            manga.text = "No"
        else:
            manga.text = "Yes"

        tree = etree.ElementTree(root)
        buffer = io.BytesIO()
        tree.write(buffer, pretty_print=True, xml_declaration=True, encoding='UTF-8')
        data = buffer.getvalue()
        buffer.close()
        return data

    @staticmethod
    def IsHaveAssignTag(tagList, assignList):
        isHave = False
        for tag in tagList:
            for noHtag in assignList:
                if noHtag.lower() in tag.lower():
                    isHave = True
                    break
        return  isHave

    @staticmethod
    def IsipAddress(hostname) -> bool:
        if isinstance(hostname, bytes):
            # IDN A-label bytes are ASCII compatible.
            hostname = hostname.decode("ascii")
        _IPV4_PAT = r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
        _IPV4_RE = re.compile("^" + _IPV4_PAT + "$")
        _HEX_PAT = "[0-9A-Fa-f]{1,4}"
        _LS32_PAT = "(?:{hex}:{hex}|{ipv4})".format(hex=_HEX_PAT, ipv4=_IPV4_PAT)
        _subs = {"hex": _HEX_PAT, "ls32": _LS32_PAT}
        _variations = [
            #                            6( h16 ":" ) ls32
            "(?:%(hex)s:){6}%(ls32)s",
            #                       "::" 5( h16 ":" ) ls32
            "::(?:%(hex)s:){5}%(ls32)s",
            # [               h16 ] "::" 4( h16 ":" ) ls32
            "(?:%(hex)s)?::(?:%(hex)s:){4}%(ls32)s",
            # [ *1( h16 ":" ) h16 ] "::" 3( h16 ":" ) ls32
            "(?:(?:%(hex)s:)?%(hex)s)?::(?:%(hex)s:){3}%(ls32)s",
            # [ *2( h16 ":" ) h16 ] "::" 2( h16 ":" ) ls32
            "(?:(?:%(hex)s:){0,2}%(hex)s)?::(?:%(hex)s:){2}%(ls32)s",
            # [ *3( h16 ":" ) h16 ] "::"    h16 ":"   ls32
            "(?:(?:%(hex)s:){0,3}%(hex)s)?::%(hex)s:%(ls32)s",
            # [ *4( h16 ":" ) h16 ] "::"              ls32
            "(?:(?:%(hex)s:){0,4}%(hex)s)?::%(ls32)s",
            # [ *5( h16 ":" ) h16 ] "::"              h16
            "(?:(?:%(hex)s:){0,5}%(hex)s)?::%(hex)s",
            # [ *6( h16 ":" ) h16 ] "::"
            "(?:(?:%(hex)s:){0,6}%(hex)s)?::",
        ]
        _IPV6_PAT = "(?:" + "|".join([x % _subs for x in _variations]) + ")"
        _UNRESERVED_PAT = r"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._\-~"
        _ZONE_ID_PAT = "(?:%25|%)(?:[" + _UNRESERVED_PAT + "]|%[a-fA-F0-9]{2})+"
        _IPV6_ADDRZ_PAT = r"\[" + _IPV6_PAT + r"(?:" + _ZONE_ID_PAT + r")?\]"
        _BRACELESS_IPV6_ADDRZ_RE = re.compile("^" + _IPV6_ADDRZ_PAT[2:-2] + "$")
        return bool(_IPV4_RE.match(hostname) or _BRACELESS_IPV6_ADDRZ_RE.match(hostname))

    @staticmethod
    def HasIpv6() -> bool:
        """Returns True if the system can bind an IPv6 address."""
        host = "::1"
        sock = None
        has_ipv6 = False
        import socket
        if socket.has_ipv6:
            # has_ipv6 returns true if cPython was compiled with IPv6 support.
            # It does not tell us if the system has IPv6 support enabled. To
            # determine that we must bind to an IPv6 address.
            # https://github.com/urllib3/urllib3/pull/611
            # https://bugs.python.org/issue658327
            try:
                sock = socket.socket(socket.AF_INET6)
                sock.bind((host, 0))
                has_ipv6 = True
            except Exception:
                pass

        if sock:
            sock.close()
        return has_ipv6

if __name__ == "__main__":
    from server import req
    reqs = req.GetLatestInfoReq2()

    Text = "wV60pmqKsG5SWYgofUhsBQVFHVvxowZJ+Hp3GooM8NoZsL8g9klKHgeiNlXqVw9IXviwHxceBOQCYmkLulZNYEk6G\/rdv5Zif644m6s1EAcbdTpia1PqD3kOuCV9ny6AjmWGitpopiHs6OD+PWVASX28VD33Vh0ngIC1L2HX+gGqeDGtB5jboRoNyodsZe21aWVFP9FwYRvCT\/iTivjUrZ40ByRad1nFfuxqn5OHkWq983jFtsIeUCnJTFBjWOGq5XMA7XmxHmz9OJKT2PR5E0gD+HHcihbGfzMeck\/RSJtwZmospTfJL\/\/WFGzR993VpSbXNLANgd1x1dlkVWp7swQhhewQM\/uVgBNIW\/HIWfB9vFQ991YdJ4CAtS9h1\/oBE3qSo+F5szfGb7iWpKINeSyHzlYWMZDCCcFfz0EHG5iE2SsxtVz7Mm+66Gz4zT30V9vW46V9L4NL+D+kuLq8++VzAO15sR5s\/TiSk9j0eRNIA\/hx3IoWxn8zHnJP0UibLLdWv0yHvy2VJm1bFinjaBrK1pG9BZc6VigqnRGY4nh6eOfPcq\/r61rtT82EdmNpfbxUPfdWHSeAgLUvYdf6ARN6kqPhebM3xm+4lqSiDXmq5h0gTnH\/3xhi\/dFtGzydwXzuoPWzF9knUNkagjG8UXYZRRDP2IcQOYvkGz7ef119vFQ991YdJ4CAtS9h1\/oB+OqsJhSzDRAaElXmoPbbJlWWD4v2Ak8bImrFw29qy3uc2DYJF3Tr7BOEx+9YzMUTFiMWl5PFnV1QfWXIpnj3wk3KfxMefHAjKD7nnsv8tNdSTlAgBpC8fN0XhSC15b7kuRVrutJMShlFEwOG5LMu57exmt5PLtON\/51Oc7GHuW72D8xT4FVV9\/Rm0zUAjTpHn9bG7C\/aFfT9GKCcoxJxsljEn8suqOayO0s1o8RmcDbqO9+sKf3y3qZCHjK4BCJMBG8nPlEsniGb1ixZVJ9yBzhYxJrSMVXtOKVcmDeHM4qObRVLIOqAq+3OHjQYjVstCl2n6Fj5O+VvRU35tJNUB3pa7THCoIHXj\/kvW+fvabkl9fNqJb\/\/dCklWVg\/KAXtBo1wq+G5R9wu7ZfE7fnW4Gm+m8oVTTC0UTAkeFga+bIgT95r2+3biocmK3MiiafE9k7e3c94Ne+fL8jeSTjewvbtLHglDAM2GGb1cDcALEvGyH+AtmsTbz+l6UqZifXEiABBK\/6zaBkSw\/AWZVWUGpS7Pcgo5FRsUUkCvMRclRg0hMLqtQAh6JK2fFzZJYhX+8JmlmmAno63LodrXvE\/l9R5CysTMpRg+4QJ5G5wj0eKVE0dw6Qw8TS7ghhFENruLNLpTS0tH7LUKSS4APnuTDzwmWnFgTzhDHOcOzQNPH7SxJgqRHCLOoevbf9rkfHoDYhrhvhNiZhsYQ3fR1vvJ18Q2vFOkDuWcIm0+ngV10T3UgduENf3ob3hZeJdW2wUxYdDcXxvsIn\/CBOF+9k5Xi7s8AuhbNuUngXYQQVpY0cLjyiabMkckPW\/UewlY4pgBCRm4ZWkMZGQDzdNXLtZ2ZoGvp6pAGbRrLCFQZolndQe\/6DhvKirsmSdYUF+2UOZ2GlRrqW3C3VCp4OjiMpHF9Ds26eSlB5AhqQp\/f+f\/96iQTOJtwHpcsIRsuoKHXNBpKBxfuALnOqv9xwpOXC2OpjHKSP9CJdVDoPaWOUpAT5o181L5RWCvhsEzY8OIsm1A+S3dIHfeZPVcV8hwXBeaQ=="
    reqs.now = 1640933310

    # Text = "gj2Slw7zsER7I+7ve1GoMmSc4sPx98spX5fE\/UMNA7KJWGBkHGkHmTdzu+d9RBbtjyGLRSoem4CBpI8V88UxLYbZiPSbA7voN9ft8h78tlXyKAlLxfR4q43FeEOZ9iqhoaZzEXKobDbRAY3oVL12xf2rY1JoGRqD1Un+iZgEEe1knOLD8ffLKV+XxP1DDQOyiVhgZBxpB5k3c7vnfUQW7UkmyWUxo3LXMCe8zmOcgncm1jJto49dAVI1pqc5YJteOQcmHglyNS\/jBhf6er7v57zoBITHb2flKWD5DFA32GBZo\/LN5d3FlymLgKLHqelbdqnIOmmclKCW0Qj1h60N1yGg3i4CRDm2CQrLfKVSUrFubNyxxx83K5aIbvZ9NubWJ7fK3G+cYCwAUE18z2Rx9gMgOaef5pvHncrWJ5ItQ3dGVB1CxpVfSk5nmBNsYSO7HoQkg\/YuoD\/n5rB8210kK5sRzcYeaJ3VdySxoJuMC3+\/TF8KtbI+INY8XQFKWWOdTEMOpHdx50C5tVCDkuwzg+XaqnZoAlqhs7I9\/umInvhanEoUO2riA\/M9guiD\/5poRmW39EWpzD8e3QaHo1nCClI40vvsrkT6g4FSRdF1bZW\/1hxh06OYndviKtyYWn85no+GTqLOx4EqgRbHHzA+XhXlkx89fFI7PcocfzMfk8CVuG2LJud\/Znr8yQOVyoXO7GXHOmLA\/4aHwA9H9V9+X1BChE\/doxZtQy9KBoPaA0Q70+NFMpez0a901kNXo01j1torXqu4qBrPVxompGJK4TjuM0DfLsIqfaOZWmw4RXomhP6AWF+4Em5B\/qTEyq99C71uTH6t10DnLIxf1EscXwM7VXyP1QKGev3LVydfllL8cTWuqyPo\/yuHj\/JtESQnLvzwIvVF8K\/RasAti1J6L\/mXD1jYpSI0R\/JKi+Fjd\/kjOeK8qZ1nhHxQFMkr6wDBKKzW7TmXqj1UUSmLJcpwSDtIKEMeeVkaYW4NciqZhfI8BPJZcgHeVLrHT8pcu+nrTnRLEvVNrsvfaCIWWIlIimDLoICFlKi82r9UxJS+7y6tIOISGKEPHrjxq2BU1ggMitnqDeMP5EGO3dk84rgF2xkiaGKB76ZxYVmxxbnozK\/YBsMhUWG93I3yE3ZqG29f7zEexTVuwAzFMVMizp8rpYx1ClCY9ITp+w0n+u7NBNg6au+npFPzKta7Dw2eYQMwWggF3bQbIjx2YpoHvx\/uQHbV4E33VR1L54RaT5y4rv77qdAlBjnTQXc1X\/LEmxJ7+1WM0Cnk+qLQ3BkcqBTcnrKumzZZgGDZBPSTPUAnUsztwmNDYmK6azJHeEe5QQiVFQC91ZWznVeZArLfH7d1cOcGK2R2Tj4CFId2OHa5QuHwLy9\/Ylxp3h0qdn6r5tXDqbK3E6s9mjL7GwIXdxJt6ocBWGNPRvJkjzERZP9\/ffBpUs10FdcUxA2BYNR3lMvuCdg4CUVX7\/576cjCg9h8P1Pfet9QOFxlrUnr2j+Dfuutg1LOYHrUy\/b64R1nUfkFR1OfdChuAP+g3HmlOQByrd4lSMEX2yKpR0YGCXiSACpWh9N35eRt6\/cnd5L5g1X9wgmCfKVItkECrndJ04vzrY4XCZZZK486ZJxbl2GBI+q65xlWNLpQ7Kvkag9gsg\/35SyPFc+pKQg0YKRlBP5dgMzs48VwW3t3hBdQlvIQJg1rvSGk4qZWRpplUOPU5lN6A\/pFmceXXRkXlsOL5Zy5UDC1okLzGJzPJPUI\/lqIiy4="
    # reqs.now = 1700559977

    # Text2 = "X+bnzYIcwF6C7Rd3T7njPI8Ls+7WOpYMYB4Jo0v3EBUxajNiDbkp63V965sLWnuQ9fBoadXgN0Wra0p5YnchwW3+be1xjXtFkch0PChn9aDCLbwt24BPd/i5ZFXyr3nKhhpI1jM7k/KVNayWyuUAhX6XmowZHUD5fOJKWvUD761pNRTi9eq+vNh1XDr3dIWInkFeK7g5aXSGaSKux2z5jUIJzw69HQ300Nf0UJV3iyHbavraaKpGzXbkPhQAsM++"
    reqs.ParseData(Text)
