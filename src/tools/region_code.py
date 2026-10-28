# coding:utf-8
""" 地区名 ↔ 二字代码

`req.GetProxyIpInfoReq(country)` 是把参数拼进子域：

    https://check.jpacg.cc/resolve?proxyip=proxyip.{country}.cmliussss.net

也就是说这里要的是 **us / jp / hk 这种二字代码**，而节点信息(`GetIpInfoReq`)只回
「国家·省份」这样的中文名。所以下拉里显示中文、真正发请求时换成代码，中间就得有
这张表；表里没有的地区退回原文本（老行为：用户自己敲什么就发什么）。
"""

# 中文国家/地区名 -> 二字代码
CountryCode = {
    # 亚太
    "日本": "jp", "韩国": "kr", "朝鲜": "kp",
    "中国香港": "hk", "香港": "hk", "中国台湾": "tw", "台湾": "tw",
    "中国澳门": "mo", "澳门": "mo", "中国大陆": "cn", "中国": "cn",
    "新加坡": "sg", "马来西亚": "my", "泰国": "th", "越南": "vn",
    "印度尼西亚": "id", "印尼": "id", "菲律宾": "ph", "印度": "in",
    "巴基斯坦": "pk", "孟加拉国": "bd", "孟加拉": "bd", "斯里兰卡": "lk",
    "尼泊尔": "np", "哈萨克斯坦": "kz", "柬埔寨": "kh", "缅甸": "mm",
    "蒙古": "mn", "乌兹别克斯坦": "uz",
    # 美洲
    "美国": "us", "加拿大": "ca", "墨西哥": "mx", "巴西": "br",
    "阿根廷": "ar", "智利": "cl", "哥伦比亚": "co", "秘鲁": "pe",
    "委内瑞拉": "ve", "厄瓜多尔": "ec", "乌拉圭": "uy", "巴拿马": "pa",
    # 欧洲
    "英国": "gb", "爱尔兰": "ie", "法国": "fr", "德国": "de",
    "荷兰": "nl", "比利时": "be", "瑞士": "ch", "奥地利": "at",
    "意大利": "it", "西班牙": "es", "葡萄牙": "pt", "波兰": "pl",
    "捷克": "cz", "斯洛伐克": "sk", "匈牙利": "hu", "罗马尼亚": "ro",
    "保加利亚": "bg", "希腊": "gr", "瑞典": "se", "挪威": "no",
    "芬兰": "fi", "丹麦": "dk", "乌克兰": "ua", "俄罗斯": "ru",
    "白俄罗斯": "by", "立陶宛": "lt", "拉脱维亚": "lv", "爱沙尼亚": "ee",
    "塞尔维亚": "rs", "克罗地亚": "hr", "斯洛文尼亚": "si", "冰岛": "is",
    "卢森堡": "lu", "摩尔多瓦": "md",
    # 中东 / 非洲
    "土耳其": "tr", "以色列": "il", "阿联酋": "ae", "阿拉伯联合酋长国": "ae",
    "沙特阿拉伯": "sa", "沙特": "sa", "卡塔尔": "qa", "科威特": "kw",
    "阿曼": "om", "约旦": "jo", "巴林": "bh", "伊朗": "ir", "伊拉克": "iq",
    "黎巴嫩": "lb", "埃及": "eg", "南非": "za", "摩洛哥": "ma",
    "尼日利亚": "ng", "肯尼亚": "ke", "突尼斯": "tn", "阿尔及利亚": "dz",
    # 大洋洲
    "澳大利亚": "au", "新西兰": "nz", "斐济": "fj",
}


def _ShortName(text):
    """ 「美国·Los Angeles」->「美国」；已经是纯名字就原样返回 """
    text = (text or "").strip()
    for sep in ("·", "・", "•", "/", "|", " - ", "-", "_"):
        if sep in text:
            return text.split(sep)[0].strip()
    return text


def RegionToCode(text):
    """ 地区名(或已是代码) -> 二字小写代码；认不出来返回 "" """
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) == 2 and text.isascii() and text.isalpha():
        return text.lower()          # 用户/配置里本来就是 "us"
    name = _ShortName(text)
    code = CountryCode.get(name)
    if code:
        return code
    if name.startswith("中国") and len(name) > 2:
        return CountryCode.get(name[2:], "")
    return ""


def RegionToName(code):
    """ 二字代码 -> 中文名(反查第一个匹配)；认不出来返回 "" """
    code = (code or "").strip().lower()
    if not code:
        return ""
    for name, value in CountryCode.items():
        if value == code and not name.startswith("中国"):
            return name
    return ""
