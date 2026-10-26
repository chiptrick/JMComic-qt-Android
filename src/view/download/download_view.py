import os
import shutil
from functools import partial

from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QAction
from PySide6.QtWidgets import QHeaderView, QAbstractItemView, QMenu, QTableWidgetItem, QMessageBox, QApplication

from config import config
from config.setting import Setting
from component.list.download_card import DownloadCard, Tr
from interface.ui_download import Ui_Download
from qt_owner import QtOwner
from task.qt_task import QtTaskBase
from tools.langconv import Converter
from tools.log import Log
from tools.status import Status
from tools.str import Str
from tools.tool import ToolUtil
from view.download.download_db import DownloadDb
from view.download.download_item import DownloadItem
from view.download.download_status import DownloadStatus


class DownloadView(QtWidgets.QWidget, Ui_Download, DownloadStatus):
    def __init__(self):
        super(self.__class__, self).__init__()
        Ui_Download.__init__(self)
        DownloadStatus.__init__(self)
        self.setupUi(self)

        # if config.Language == "English":
        #     HorizontalHeaderLabels = ["id", "Title", "Download Status", "Download Progress", "Download Chapters", "Download Speed", "Convert Progress", "Covert Chapters", "Covert Time", "Convert Status"]
        # else:
        #     HorizontalHeaderLabels = ["id", "标题", "下载状态", "下载进度", "下载章节", "下载速度", "转换进度", "转换章节", "转换耗时", "转换状态"]


        self.tableWidget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tableWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        # 方案A：一行 = 一张卡片。表格退化成"单列 + 卡片 cellWidget"的数据/交互层
        # （选择、右键菜单、双击、QScroller 全部沿用原来的行为），显示由 DownloadCard 负责。
        self.InitCardTable()
        self.InitSortBar()
        self.timer = QTimer(self.tableWidget)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.TimeOutHandler)

        self.failTimer = QTimer(self.tableWidget)
        self.failTimer.setInterval(60*1000)
        self.failTimer.timeout.connect(self.CheckFailReDownload)

        # self.settings = QSettings('download.ini', QSettings.IniFormat)
        # self.InitSetting()

        self.tableWidget.customContextMenuRequested.connect(self.SelectMenu)

        self.tableWidget.doubleClicked.connect(self.OpenBookInfo)
        self.tableWidget.itemSelectionChanged.connect(self.SyncCardSelection)
        self.radioButton.setChecked(Setting.DownloadAuto.value)
        datas = self.db.LoadDownload(self)
        self.redownloadRadio.clicked.connect(self.SwitchReDownload)
        self.skipPic.clicked.connect(self.SwitchSkipPic)
        self.webp2Png.clicked.connect(self.SwitchWebp2png)
        for task in datas.values():
            self.downloadDict[task.bookId] = task
            if not task.epsIds:
                Log.Warn("not fond task, epsIds, bookId:{}, title:{}".format(task.bookId, task.title))
                continue

            rowCont = self.tableWidget.rowCount()
            task.tableRow = rowCont
            self.tableWidget.insertRow(rowCont)
            self.RepairData(task)
            self.UpdateTableItem(task)
        self.someDownButton.clicked.connect(QtOwner().OpenSomeDownload)
        self.comboBox.currentIndexChanged.connect(self.CheckHideItem)
        self.lineEdit.textChanged.connect(self.SearchTextChange)
        self.searchText = ""
        self.UpdateCount()

    # ---------------- 卡片列表（方案 A） ----------------
    def InitCardTable(self):
        """ 表格退化成单列卡片容器：隐藏表头/网格/行号，行高由卡片内容算 """
        table = self.tableWidget
        # 列数保持 11、只隐藏 1~10 列：生成代码 ui_download.retranslateUi() 会去
        # horizontalHeaderItem(0..10) 改表头文字，直接 setColumnCount(1) 会让那些
        # item 变成 None —— 启动/切语言时 RetranslateUi 就 AttributeError 崩掉。
        # 隐藏列不参与布局，可见效果与"单列"完全一致。
        table.setColumnCount(11)
        for index in range(1, 11):
            table.setColumnHidden(index, True)
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.verticalHeader().setMinimumSectionSize(1)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setFrameShape(QtWidgets.QFrame.NoFrame)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # 主题里 QHeaderView::section 有 padding:0 20px、QTableView 有 1px 边框；
        # 卡片自己有左右留白，这里全部清掉，否则卡片两侧会被裁
        # color:transparent —— 第 0 列还存着 bookId(命中/数据用)，但卡片是透明底，
        # 不把它画成透明的话，表格会在卡片下面再画一遍 ID，和标题第二行叠在一起
        table.setStyleSheet("QTableWidget{background:transparent;border:none;}"
                            "QTableWidget::item{border:none;padding:0;color:transparent;}"
                            "QTableWidget::item:selected{color:transparent;}")
        # 唯一的那一列必须吃满视口：默认列宽 100，卡片会被挤成手指宽的一条
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setStretchLastSection(True)
        self._syncGuard = False
        # 视口宽度变了(旋转/滚动条出现)：卡片标题折行与行高都要重算
        table.viewport().installEventFilter(self)
        # 表头去掉之后，空列表就是一块白板 —— 给个占位提示
        self.emptyLabel = QtWidgets.QLabel(Tr("暂无下载记录"), table.viewport())
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.setStyleSheet("color:#7C858E;background:transparent;")
        self.emptyLabel.hide()

    def InitSortBar(self):
        """ 「共 N 项 + 排序」细条：表头没了，排序入口挪到这里 """
        bar = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(13, 2, 13, 2)
        layout.setSpacing(6)
        self.countLabel = QtWidgets.QLabel(bar)
        self.sortLabel = QtWidgets.QLabel(Tr("排序"), bar)
        self.sortCombo = QtWidgets.QComboBox(bar)
        for text in (Tr("添加时间"), Tr("标题"), Tr("下载状态"), Tr("转换状态")):
            self.sortCombo.addItem(text)
        layout.addWidget(self.countLabel, 0)
        layout.addStretch(1)
        layout.addWidget(self.sortLabel, 0)
        layout.addWidget(self.sortCombo, 0)
        self.gridLayout.addWidget(bar, 4, 0, 1, 1)
        self.sortCombo.currentIndexChanged.connect(self.SortBy)

    def SyncCardSelection(self):
        """ 表格选中状态 -> 卡片高亮（卡片本身鼠标穿透，选中仍由表格决定） """
        table = self.tableWidget
        selected = set()
        for index in table.selectedIndexes():
            selected.add(index.row())
        for row in range(table.rowCount()):
            card = table.cellWidget(row, 0)
            if card is not None:
                card.SetSelected(row in selected)

    def eventFilter(self, obj, event):
        try:
            if obj is self.tableWidget.viewport() and event.type() == QEvent.Type.Resize:
                if getattr(self, "emptyLabel", None) is not None:
                    self.emptyLabel.setGeometry(self.tableWidget.viewport().rect())
                if not self._syncGuard:
                    self._syncGuard = True
                    QTimer.singleShot(0, self.DeferredSyncCards)
        except Exception as es:
            Log.Error(es)
        return QtWidgets.QWidget.eventFilter(self, obj, event)

    def DeferredSyncCards(self):
        try:
            self.SyncCardHeights()
        finally:
            self._syncGuard = False

    def SyncCardHeights(self):
        """ 宽度变了(旋转/窗口缩放)：重算标题折行与行高 """
        table = self.tableWidget
        for row in range(table.rowCount()):
            card = table.cellWidget(row, 0)
            if card is None:
                continue
            card.Relayout()
            self.SyncRowHeight(row, card)

    def SyncRowHeight(self, row, card=None):
        table = self.tableWidget
        if card is None:
            card = table.cellWidget(row, 0)
        if card is None:
            return
        height = card.HeightForWidth(table.viewport().width())
        if height > 0 and table.rowHeight(row) != height:
            table.setRowHeight(row, height)

    def UpdateCount(self):
        if getattr(self, "countLabel", None) is None:
            return
        total = self.tableWidget.rowCount()
        hidden = 0
        for row in range(total):
            if self.tableWidget.isRowHidden(row):
                hidden += 1
        if hidden:
            self.countLabel.setText(Tr("共 {} 项 · 显示 {} 项").format(total, total - hidden))
        else:
            self.countLabel.setText(Tr("共 {} 项").format(total))
        if getattr(self, "emptyLabel", None) is not None:
            self.emptyLabel.setGeometry(self.tableWidget.viewport().rect())
            self.emptyLabel.setVisible(total == 0)

    def SortBy(self, index):
        """ 排序（表头隐藏后由下拉框触发）：重建行，行号随之更新 """
        tasks = [t for t in self.downloadDict.values() if isinstance(t, DownloadItem)]
        try:
            if index == 0:
                tasks.sort(key=lambda t: t.tick, reverse=True)
            elif index == 1:
                tasks.sort(key=lambda t: (t.title or "").lower())
            elif index == 2:
                tasks.sort(key=lambda t: t.GetStatusMsg() or "")
            else:
                tasks.sort(key=lambda t: t.GetConvertStatusMsg() or "")
        except Exception as es:
            Log.Error(es)
        self.RebuildRows(tasks)

    def RebuildRows(self, tasks=None):
        """ 清空重排所有行（排序/重建用）：表格行号与卡片一一对应 """
        table = self.tableWidget
        table.setRowCount(0)
        if tasks is None:
            tasks = [t for t in self.downloadDict.values() if isinstance(t, DownloadItem)]
        for row, task in enumerate(tasks):
            task.tableRow = row
            table.insertRow(row)
            self.UpdateTableItem(task)
        self.CheckHideItem()
        self.UpdateCount()

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        # 布局跑完才有真实宽度
        QTimer.singleShot(0, self.SyncCardHeights)

    # 修复下数据
    def RepairData(self, task):
        assert isinstance(task, DownloadItem)
        task.status = self.GetNewStatus(task.status)
        task.convertStatus = self.GetNewStatus(task.convertStatus)
        if task.status != task.Success:
            task.status = task.Pause
        if task.convertStatus != task.ConvertSuccess:
            task.convertStatus = task.Pause

        for info in task.epsInfo.values():
            # 如果下载完成了，要修改下 curPreDownloadIndex和 curPreConvertId
            if task.status == task.Success:
                info.curPreDownloadIndex = info.picCnt
            if task.convertStatus == task.ConvertSuccess:
                info.curPreConvertId = info.picCnt
        return

    def GetNewStatus(self, status):
        if status.isnumeric():
            return int(status)
        # 兼容老數據
        infos = [DownloadItem.Success, DownloadItem.Downloading, DownloadItem.Waiting, Str.ReadingPicture, Str.Reading, Str.ReadingEps, Str.NotFound,
         DownloadItem.Pause, DownloadItem.Error, DownloadItem.ConvertSuccess, DownloadItem.Converting]
        for i in infos:
            if Str.GetStr(i) == status:
                return i
        return DownloadItem.Pause

    def Close(self):
        self.timer.stop()
        self.failTimer.stop()

    def Init(self):
        self.timer.start()
        self.failTimer.start()
        self.redownloadRadio.setCheckable(True)
        self.redownloadRadio.setChecked(bool(Setting.IsReDownload.value))
        self.webp2Png.setCheckable(True)
        self.webp2Png.setChecked(bool(Setting.WebpToPng.value))
        self.skipPic.setCheckable(True)
        self.skipPic.setChecked(bool(Setting.IsSkipPic.value))

    def GetDownloadEpsInfo(self, bookId, epsId):
        info = self.GetDownloadInfo(bookId)
        if not info:
            return False
        return info.epsInfo.get(epsId)

    def GetDownloadInfo(self, bookId):
        return self.downloadDict.get(bookId)

    def IsDownloadEpsId(self, bookId, epsId):
        info = self.GetDownloadInfo(bookId)
        if not info:
            return False
        return epsId in info.epsIds

    def GetDownloadEpsId(self, bookId):
        if bookId not in self.downloadDict:
            return []
        return self.downloadDict[bookId].epsIds

    # def GetDownloadCompleteEpsId(self, bookId):
    #     if bookId not in self.downloadDict:
    #         return []
    #     return self.downloadDict[bookId].GetDownloadCompleteEpsId()

    def GetDownloadWaifu2xFilePath(self, bookId, epsId, index):
        if bookId not in self.downloadDict:
            return ""
        task = self.downloadDict[bookId]
        if epsId not in task.epsInfo:
            return ""
        epsTitle = task.epsInfo[epsId].epsTitle
        convertPath = os.path.join(task.convertPath, ToolUtil.GetCanSaveName(epsTitle))
        return os.path.join(convertPath, "{:04}".format(index + 1))

    def GetDownloadFilePath(self, bookId, epsId, index):
        if bookId not in self.downloadDict:
            return ""
        task = self.downloadDict[bookId]
        if epsId not in task.epsInfo:
            return ""
        epsTitle = task.epsInfo[epsId].epsTitle
        savePath = os.path.join(task.savePath, ToolUtil.GetCanSaveName(epsTitle))
        return os.path.join(savePath, "{:04}".format(index + 1))

    def SwitchCurrent(self, **kwargs):
        pass

    def AddDownload(self, bookId, downloadIds, isWaifu2x=False):
        if not downloadIds:
            return
        bookId = str(bookId)
        if bookId not in self.downloadDict:
            task = DownloadItem()
            task.bookId = bookId
            self.downloadDict[task.bookId] = task
            for epsId in downloadIds:
                if epsId in task.epsIds:
                    continue
                task.epsIds.append(epsId)

            rowCont = self.tableWidget.rowCount()
            task.tableRow = rowCont
            self.tableWidget.insertRow(rowCont)
            self.SetNewStatus(task, task.Waiting)
            if Setting.DownloadAuto.value or isWaifu2x:
                self.SetNewCovertStatus(task, task.Waiting)
        else:
            task = self.downloadDict.get(bookId)
            downloadIds.sort()
            for epsId in downloadIds:
                if epsId in task.epsIds:
                    continue
                task.epsIds.append(epsId)

            if task.status == task.Success:
                self.SetNewStatus(task, task.Waiting)
            if task.convertStatus == task.ConvertSuccess:
                if Setting.DownloadAuto.value or isWaifu2x:
                    self.SetNewCovertStatus(task, task.Waiting)
                else:
                    self.SetNewCovertStatus(task, task.Pause)

        self.UpdateTableItem(task)
        self.UpdateCount()
        self.db.AddDownloadDB(task)
        return True

    def UpdateTableItem(self, info):
        """ 刷新一行：表格第 0 列只放 bookId(数据/命中用)，显示交给卡片 """
        assert isinstance(info, DownloadItem)
        row = info.tableRow
        table = self.tableWidget
        if row < 0 or row >= table.rowCount():
            return

        item = table.item(row, 0)
        if item is None:
            item = QTableWidgetItem(str(info.bookId))
            table.setItem(row, 0, item)
        elif item.text() != str(info.bookId):
            item.setText(str(info.bookId))
        if item.toolTip() != (info.title or ""):
            item.setToolTip(info.title or "")

        card = table.cellWidget(row, 0)
        if not isinstance(card, DownloadCard):
            card = DownloadCard(table.viewport())
            table.setCellWidget(row, 0, card)
            card.SetSelected(self.IsRowSelected(row))
        card.Update(info)
        self.SyncRowHeight(row, card)
        return

    def IsRowSelected(self, row):
        for index in self.tableWidget.selectedIndexes():
            if index.row() == row:
                return True
        return False

    def RemoveRecord(self, bookId):
        task = self.downloadDict.get(bookId)
        if not task:
            return
        assert isinstance(task, DownloadItem)
        if task in self.downloadingList:
            self.downloadingList.remove(task)
        if task in self.downloadList:
            self.downloadList.remove(task)
        if task in self.convertList:
            self.convertList.remove(task)
        if task in self.convertingList:
            self.convertingList.remove(task)
        self.downloadDict.pop(bookId)
        if task.tableRow >= 0:
            self.tableWidget.removeRow(task.tableRow)
            # 删掉一行后，后面所有 task.tableRow 都要前移（不重算会串行/越界）
            self.UpdateTableRow()
        self.UpdateCount()
        self.db.DelDownloadDB(bookId)

    def UpdateTableRow(self):
        count = self.tableWidget.rowCount()
        for i in range(count):
            bookId = self.tableWidget.item(i, 0).text()
            info = self.downloadDict.get(bookId)
            if info:
                info.tableRow = i

    # 右键菜单
    def SelectMenu(self, pos):
        index = self.tableWidget.indexAt(pos)
        openDirAction = QAction(Str.GetStr(Str.OpenDir), self)
        openDirAction.triggered.connect(self.ClickOpenFilePath)

        pauseAction = QAction(Str.GetStr(Str.Pause), self)
        pauseAction.triggered.connect(self.ClickPause)

        removeAction = QAction(Str.GetStr(Str.DeleteRecord), self)
        removeAction.triggered.connect(self.DelRecording)

        copyAction = QAction(Str.GetStr(Str.CopyIdAndTitle), self)
        copyAction.triggered.connect(self.CopyIdAndTitle)

        removeFileAction = QAction(Str.GetStr(Str.DeleteRecordFile), self)
        removeFileAction.triggered.connect(self.DelRecordingAndFile)

        # self.openDirAction = QAction("打开目录", self)
        # self.openDirAction.triggered.connect(self.ClickOpenFilePath)

        selectEpsAction = QAction(Str.GetStr(Str.SelectEps), self)
        selectEpsAction.triggered.connect(self.ClickDownloadEps)

        startAction = QAction(Str.GetStr(Str.Start), self)
        startAction.triggered.connect(self.ClickStart)

        startConvertAction = QAction(Str.GetStr(Str.StartConvert), self)
        startConvertAction.triggered.connect(self.ClickConvertStart)

        pauseConvertAction = QAction(Str.GetStr(Str.PauseConvert), self)
        pauseConvertAction.triggered.connect(self.ClickConvertPause)

        addLocalAction = QAction(Str.GetStr(Str.ImportLocal), self)
        addLocalAction.triggered.connect(self.ClickAddLocalBook)

        if index.isValid():
            selected = self.tableWidget.selectedIndexes()
            selectRows = set()
            for index in selected:
                selectRows.add(index.row())
            if not selectRows:
                return
            if len(selectRows) == 1:
                # 单选
                row = selectRows.pop()
                col = 0
                bookId = self.tableWidget.item(row, col).text()
                task = self.downloadDict.get(bookId)
                if not task:
                    return
                title = task.title

                menu = QMenu(self.tableWidget)

                menu.addAction(openDirAction)
                menu.addAction(selectEpsAction)
                assert isinstance(task, DownloadItem)
                if task.status in [task.Pause, task.Error]:
                    menu.addAction(startAction)
                elif task.status in [task.Downloading, task.Waiting]:
                    menu.addAction(pauseAction)

                if task.convertStatus in [task.Converting, task.Waiting]:
                    menu.addAction(pauseConvertAction)
                elif task.convertStatus in [task.Pause, task.Error]:
                    menu.addAction(startConvertAction)
                if title:
                    nas = QMenu(Str.GetStr(Str.NetNas))
                    nasDict = QtOwner().owner.nasView.nasDict
                    if not nasDict:
                        action = nas.addAction(Str.GetStr(Str.CvSpace))
                        action.setEnabled(False)
                    else:
                        for k, v in nasDict.items():
                            action = nas.addAction(v.showTitle)
                            if QtOwner().nasView.IsInUpload(k, bookId):
                                action.setEnabled(False)
                            action.triggered.connect(partial(self.NasUploadHandler, title, k, bookId))
                    menu.addMenu(nas)

            else:
                menu = QMenu(self.tableWidget)
                menu.addAction(startAction)
                menu.addAction(pauseAction)
                menu.addAction(startConvertAction)
                menu.addAction(pauseConvertAction)

            menu.addAction(addLocalAction)
            menu.addAction(copyAction)
            menu.addAction(removeAction)
            menu.addAction(removeFileAction)
            menu.exec_(QCursor.pos())
        pass

    def NasUploadHandler(self, title, nasId, bookId):
        QtOwner().nasView.AddNasUpload2(title, nasId, bookId)
        return

    def OnDownloadRootChanged(self, oldRoot="", newRoot=""):
        """ 下载根目录变了：内存与数据库里的 savePath/convertPath 一起挪到新根

        不去重算"标题->目录名"是对的：用户可能开着"作者目录"命名，重算要再走一遍
        Title/Author 状态；直接做前缀替换既准确又不会碰到没下载完的项。
        """
        if not newRoot:
            newRoot = Setting.GetDownloadRoot()
        if not oldRoot or oldRoot == newRoot:
            return 0
        changed = 0
        try:
            from tools import vfs
            for task in self.downloadDict.values():
                if not isinstance(task, DownloadItem):
                    continue
                touched = False
                for attr in ("savePath", "convertPath"):
                    value = getattr(task, attr, "") or ""
                    if not value:
                        continue
                    if value == oldRoot or value.startswith(oldRoot + "/"):
                        setattr(task, attr, newRoot + value[len(oldRoot):])
                        touched = True
                if touched:
                    changed += 1
                    self.db.AddDownloadDB(task)
                    try:
                        self.UpdateTableItem(task)
                    except Exception:
                        pass
        except Exception as es:
            Log.Error(es)
        Log.Warn("download path: 重定向 {} 个下载项 {} -> {}".format(changed, oldRoot, newRoot))
        return changed

    def ClickOpenFilePath(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        # 只去第一个
        row = selectRows.pop()
        col = 0
        bookId = self.tableWidget.item(row, col).text()
        task = self.downloadDict.get(bookId)
        assert isinstance(task, DownloadItem)
        folder = os.path.dirname(task.savePath)
        from tools import vfs
        ok, reason = vfs.OpenInFileManager(folder)
        if not ok:
            # 应用专属目录其它应用看不到(也没有 file:// 处理者)：直接告诉用户怎么改
            if reason == "sandbox":
                QtOwner().ShowMsg(Str.GetStr(Str.SetDir))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        return

    def ClickPause(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        for row in selectRows:
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.status in [task.Success]:
                continue
            self.SetNewStatus(task, task.Pause)
        return

    def ClickConvertPause(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        for row in selectRows:
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.convertStatus in [task.ConvertSuccess]:
                continue
            self.SetNewCovertStatus(task, task.Pause)
        return

    def ClickAddLocalBook(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        allFilePath = []
        for row in selectRows:
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            assert isinstance(task, DownloadItem)
            if task.savePath:
                allFilePath.append(os.path.dirname(task.savePath))
        QtOwner().localReadView.ImportDownloadDirs(allFilePath)
        return

    def ClickDownloadEps(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        for row in selectRows:
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            QtOwner().OpenEpsInfo(task.bookId)

        return

    def ClickStart(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        for row in selectRows:
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.status not in [task.Pause, task.Error]:
                continue
            self.SetNewStatus(task, task.Waiting)

            if Setting.DownloadAuto.value:
                if task.convertStatus not in [task.Pause, task.Error]:
                    continue
                self.SetNewCovertStatus(task, task.Waiting)

    def ClickConvertStart(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        for row in selectRows:
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.convertStatus not in [task.Pause, task.Error]:
                continue
            self.SetNewCovertStatus(task, task.Waiting)

    def DelRecording(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        isRun = QMessageBox.information(self, Str.GetStr(Str.Delete), Str.GetStr(Str.ConfirmDeleteRecord), QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)
        if isRun != QtWidgets.QMessageBox.Yes:
            return

        for row in sorted(selectRows, reverse=True):
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            self.RemoveRecord(bookId)
        self.UpdateTableRow()

    def CopyIdAndTitle(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        text = ""
        for row in sorted(selectRows, reverse=True):
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            info = self.downloadDict.get(bookId)
            text += "JM{}-{}\r\n".format(bookId, info.title)
        clipboard = QApplication.clipboard()
        data = text.strip("\r\n")
        clipboard.setText(data)
        QtOwner().ShowMsg(Str.GetStr(Str.CopySuc))
        return

    def DelRecordingAndFile(self):
        isClear = QMessageBox.information(self, Str.GetStr(Str.DeleteRecord), Str.GetStr(Str.ConfirmDeleteRecordAndFile), QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No)
        if isClear != QtWidgets.QMessageBox.Yes:
            return
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if not selectRows:
            return
        try:
            for row in sorted(selectRows, reverse=True):
                col = 0
                bookId = self.tableWidget.item(row, col).text()
                bookInfo = self.downloadDict.get(bookId)
                if not bookInfo:
                    continue
                self.RemoveRecord(bookId)
                path = os.path.dirname(bookInfo.savePath)
                # 目录可能在 SAF 里：vfs 会走 ContentResolver 递归删
                from tools import vfs
                vfs.RemoveTree(path)

        except Exception as es:
            Log.Error(es)
        self.UpdateTableRow()

    def OpenBookInfo(self):
        selected = self.tableWidget.selectedIndexes()
        selectRows = set()
        for index in selected:
            selectRows.add(index.row())
        if len(selectRows) > 1:
            return
        if len(selectRows) <= 0:
            return
        row = list(selectRows)[0]
        col = 0
        bookId = self.tableWidget.item(row, col).text()
        task = self.downloadDict.get(bookId)
        bookName = task.title if task else ""
        if not bookId:
            return
        QtOwner().OpenBookInfo(bookId, bookName)

    def StartAll(self):
        for row in range(self.tableWidget.rowCount()):
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.status not in [task.Pause, task.Error]:
                continue
            self.SetNewStatus(task, task.Waiting)
            if Setting.DownloadAuto.value:
                if task.convertStatus not in [task.Pause, task.Error]:
                    continue
                self.SetNewCovertStatus(task, task.Waiting)

    def StopAll(self):
        for row in range(self.tableWidget.rowCount()):
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.status in [task.Success]:
                continue
            self.SetNewStatus(task, task.Pause)

    def StartConvertAll(self):
        for row in range(self.tableWidget.rowCount()):
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.convertStatus not in [task.Pause, task.Error]:
                continue
            self.SetNewCovertStatus(task, task.Waiting)

    def StopConvertAll(self):
        for row in range(self.tableWidget.rowCount()):
            col = 0
            bookId = self.tableWidget.item(row, col).text()
            task = self.downloadDict.get(bookId)
            if not task:
                continue
            if task.convertStatus in [task.ConvertSuccess]:
                continue
            self.SetNewCovertStatus(task, task.Pause)

    def SetAutoConvert(self):
        Setting.DownloadAuto.SetValue(int(self.radioButton.isChecked()))

    def SwitchReDownload(self):
        Setting.IsReDownload.SetValue(int(self.redownloadRadio.isChecked()))

    def SwitchSkipPic(self):
        Setting.IsSkipPic.SetValue(int(self.skipPic.isChecked()))

    def SwitchWebp2png(self):
        Setting.WebpToPng.SetValue(int(self.webp2Png.isChecked()))

    def CheckFailReDownload(self):
        if not Setting.IsReDownload.value:
            return
        reDownload = []
        for download in self.downloadDict.values():
            assert isinstance(download, DownloadItem)
            if download.status == download.Error:
                reDownload.append(download)
        for download in reDownload:
            self.SetNewStatus(download, DownloadItem.Waiting)

    def SearchTextChange(self, text):
        self.searchText = Converter('zh-hans').convert(text)
        self.CheckHideItem()

    def CheckHideItem(self):
        sortId = self.comboBox.currentIndex()
        count = self.tableWidget.rowCount()
        for i in range(count):
            bookId = self.tableWidget.item(i, 0).text()
            info = self.downloadDict.get(bookId)
            if info:
                assert isinstance(info, DownloadItem)
                isFind = False
                if self.searchText:
                    if self.searchText in str(info.bookId):
                        isFind = True
                    if self.searchText in Converter('zh-hans').convert(info.title):
                        isFind = True
                    if self.searchText in Converter('zh-hans').convert(info.author):
                        isFind = True
                else:
                    isFind = True

                if sortId == 0:
                    if isFind:
                        self.tableWidget.setRowHidden(i, False)
                    else:
                        self.tableWidget.setRowHidden(i, True)
                elif sortId == 1:
                    if info.status == DownloadItem.Success or not isFind:
                        self.tableWidget.setRowHidden(i, True)
                    else:
                        self.tableWidget.setRowHidden(i, False)
                elif sortId == 2:
                    if info.status == DownloadItem.Success and isFind:
                        self.tableWidget.setRowHidden(i, False)
                    else:
                        self.tableWidget.setRowHidden(i, True)
        self.UpdateCount()
