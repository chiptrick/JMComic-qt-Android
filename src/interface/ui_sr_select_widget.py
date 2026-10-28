# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ui_sr_select_widget.ui'
##
## Created by: Qt User Interface Compiler version 6.5.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSizePolicy, QTableWidgetItem,
    QVBoxLayout, QWidget)

from component.widget.sr_model_table import SrModelTable
import images_rc

class Ui_SrSelect(object):
    def setupUi(self, SrSelect):
        if not SrSelect.objectName():
            SrSelect.setObjectName(u"SrSelect")
        SrSelect.resize(673, 560)
        SrSelect.setMinimumSize(QSize(320, 0))
        self.verticalLayout = QVBoxLayout(SrSelect)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.label_4 = QLabel(SrSelect)
        self.label_4.setObjectName(u"label_4")
        font = QFont()
        font.setPointSize(9)
        self.label_4.setFont(font)
        self.label_4.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_4)

        self.label = QLabel(SrSelect)
        self.label.setObjectName(u"label")
        self.label.setFont(font)
        self.label.setWordWrap(True)

        self.verticalLayout.addWidget(self.label)

        self.tableWidget = SrModelTable(SrSelect)
        if (self.tableWidget.columnCount() < 3):
            self.tableWidget.setColumnCount(3)
        __qtablewidgetitem = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        self.tableWidget.setObjectName(u"tableWidget")
        self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tableWidget.setSelectionMode(QAbstractItemView.NoSelection)
        self.tableWidget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tableWidget.setShowGrid(False)
        self.tableWidget.setSortingEnabled(False)
        self.tableWidget.horizontalHeader().setVisible(True)
        self.tableWidget.horizontalHeader().setCascadingSectionResizes(False)
        self.tableWidget.horizontalHeader().setDefaultSectionSize(80)
        self.tableWidget.horizontalHeader().setHighlightSections(False)
        self.tableWidget.horizontalHeader().setProperty("showSortIndicator", False)
        self.tableWidget.horizontalHeader().setStretchLastSection(False)
        self.tableWidget.verticalHeader().setVisible(False)
        self.tableWidget.verticalHeader().setDefaultSectionSize(40)

        self.verticalLayout.addWidget(self.tableWidget)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.saveButton = QPushButton(SrSelect)
        self.saveButton.setObjectName(u"saveButton")
        self.saveButton.setMaximumSize(QSize(150, 30))
        self.saveButton.setStyleSheet(u"")

        self.horizontalLayout_3.addWidget(self.saveButton)

        self.closeButton = QPushButton(SrSelect)
        self.closeButton.setObjectName(u"closeButton")
        self.closeButton.setMaximumSize(QSize(150, 30))

        self.horizontalLayout_3.addWidget(self.closeButton)


        self.verticalLayout.addLayout(self.horizontalLayout_3)


        self.retranslateUi(SrSelect)

        QMetaObject.connectSlotsByName(SrSelect)
    # setupUi

    def retranslateUi(self, SrSelect):
        SrSelect.setWindowTitle(QCoreApplication.translate("SrSelect", u"Form", None))
        self.label_4.setText(QCoreApplication.translate("SrSelect", u"\u652f\u6301 Waifu2x / Real-CUGAN / Real-ESRGAN\uff08\u4e0d\u652f\u6301 CPU\uff09", None))
        self.label.setText(QCoreApplication.translate("SrSelect", u"\u300c\u6a21\u578b\u300d\u5217\u662f\u539f\u59cb\u6a21\u578b ID\uff1b\u70b9\u300c\u8017\u65f6\u300d\u8868\u5934\u53ef\u5e73\u94fa\u6392\u5e8f", None))
        ___qtablewidgetitem = self.tableWidget.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("SrSelect", u"\u6a21\u578b", None));
        ___qtablewidgetitem1 = self.tableWidget.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("SrSelect", u"\u8017\u65f6", None));
        ___qtablewidgetitem2 = self.tableWidget.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("SrSelect", u"\u63cf\u8ff0", None));
        self.saveButton.setText(QCoreApplication.translate("SrSelect", u"\u786e\u5b9a", None))
#if QT_CONFIG(shortcut)
        self.saveButton.setShortcut(QCoreApplication.translate("SrSelect", u"Return", None))
#endif // QT_CONFIG(shortcut)
        self.closeButton.setText(QCoreApplication.translate("SrSelect", u"\u5173\u95ed", None))
    # retranslateUi

