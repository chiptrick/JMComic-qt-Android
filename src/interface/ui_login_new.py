# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ui_login_new.ui'
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
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QCommandLinkButton,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QRadioButton,
    QSizePolicy, QSpacerItem, QTabWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget)

from component.box.wheel_combo_box import WheelComboBox
from component.line_edit.tip_line_edit import TipLineEdit
from component.scroll_area.smooth_scroll_area import SmoothScrollArea
from component.tab.base_table_widget import BaseTableWidget
import images_rc

class Ui_LoginNew(object):
    def setupUi(self, LoginNew):
        if not LoginNew.objectName():
            LoginNew.setObjectName(u"LoginNew")
        LoginNew.resize(722, 690)
        self.horizontalLayout_3 = QHBoxLayout(LoginNew)
        self.horizontalLayout_3.setSpacing(0)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.tabWidget = QTabWidget(LoginNew)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tab = QWidget()
        self.tab.setObjectName(u"tab")
        self.verticalLayout_3 = QVBoxLayout(self.tab)
        self.verticalLayout_3.setSpacing(12)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_3.setContentsMargins(-1, 9, 9, 9)
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_2)

        self.widget = QWidget(self.tab)
        self.widget.setObjectName(u"widget")
        self.verticalLayout = QVBoxLayout(self.widget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer)

        self.label_5 = QLabel(self.widget)
        self.label_5.setObjectName(u"label_5")

        self.verticalLayout.addWidget(self.label_5)

        self.userEdit_2 = QLineEdit(self.widget)
        self.userEdit_2.setObjectName(u"userEdit_2")

        self.verticalLayout.addWidget(self.userEdit_2)

        self.label_6 = QLabel(self.widget)
        self.label_6.setObjectName(u"label_6")

        self.verticalLayout.addWidget(self.label_6)

        self.passwdEdit_2 = QLineEdit(self.widget)
        self.passwdEdit_2.setObjectName(u"passwdEdit_2")
        self.passwdEdit_2.setEchoMode(QLineEdit.Password)

        self.verticalLayout.addWidget(self.passwdEdit_2)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.saveBox = QCheckBox(self.widget)
        self.saveBox.setObjectName(u"saveBox")

        self.horizontalLayout_2.addWidget(self.saveBox)

        self.autoBox = QCheckBox(self.widget)
        self.autoBox.setObjectName(u"autoBox")

        self.horizontalLayout_2.addWidget(self.autoBox)

        self.autoSign = QCheckBox(self.widget)
        self.autoSign.setObjectName(u"autoSign")

        self.horizontalLayout_2.addWidget(self.autoSign)


        self.verticalLayout.addLayout(self.horizontalLayout_2)

        self.loginButton = QPushButton(self.widget)
        self.loginButton.setObjectName(u"loginButton")

        self.verticalLayout.addWidget(self.loginButton)

        self.verticalSpacer_2 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer_2)


        self.horizontalLayout.addWidget(self.widget)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)


        self.verticalLayout_3.addLayout(self.horizontalLayout)

        self.tabWidget.addTab(self.tab, "")
        self.tab_2 = QWidget()
        self.tab_2.setObjectName(u"tab_2")
        self.verticalLayout_4 = QVBoxLayout(self.tab_2)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.horizontalLayout_4.addItem(self.horizontalSpacer_3)

        self.scrollArea_2 = SmoothScrollArea(self.tab_2)
        self.scrollArea_2.setObjectName(u"scrollArea_2")
        self.scrollArea_2.setWidgetResizable(True)
        self.scrollAreaWidgetContents_2 = QWidget()
        self.scrollAreaWidgetContents_2.setObjectName(u"scrollAreaWidgetContents_2")
        self.scrollAreaWidgetContents_2.setGeometry(QRect(0, 0, 306, 234))
        self.verticalLayout_8 = QVBoxLayout(self.scrollAreaWidgetContents_2)
        self.verticalLayout_8.setObjectName(u"verticalLayout_8")
        self.label = QLabel(self.scrollAreaWidgetContents_2)
        self.label.setObjectName(u"label")

        self.verticalLayout_8.addWidget(self.label)

        self.linkLayout = QVBoxLayout()
        self.linkLayout.setObjectName(u"linkLayout")

        self.verticalLayout_8.addLayout(self.linkLayout)

        self.horizontalLayout_5 = QHBoxLayout()
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.user = QLabel(self.scrollAreaWidgetContents_2)
        self.user.setObjectName(u"user")
        self.user.setMinimumSize(QSize(80, 0))
        self.user.setMaximumSize(QSize(60, 16777215))
        self.user.setLayoutDirection(Qt.LeftToRight)
        self.user.setAlignment(Qt.AlignLeading|Qt.AlignLeft|Qt.AlignVCenter)

        self.horizontalLayout_5.addWidget(self.user)

        self.userEdit = QLineEdit(self.scrollAreaWidgetContents_2)
        self.userEdit.setObjectName(u"userEdit")
        self.userEdit.setMinimumSize(QSize(200, 0))

        self.horizontalLayout_5.addWidget(self.userEdit)


        self.verticalLayout_8.addLayout(self.horizontalLayout_5)

        self.horizontalLayout_6 = QHBoxLayout()
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.name = QLabel(self.scrollAreaWidgetContents_2)
        self.name.setObjectName(u"name")
        self.name.setMinimumSize(QSize(80, 0))
        self.name.setMaximumSize(QSize(60, 16777215))
        self.name.setAlignment(Qt.AlignLeading|Qt.AlignLeft|Qt.AlignVCenter)

        self.horizontalLayout_6.addWidget(self.name)

        self.nameEdit = QLineEdit(self.scrollAreaWidgetContents_2)
        self.nameEdit.setObjectName(u"nameEdit")

        self.horizontalLayout_6.addWidget(self.nameEdit)


        self.verticalLayout_8.addLayout(self.horizontalLayout_6)

        self.horizontalLayout_19 = QHBoxLayout()
        self.horizontalLayout_19.setObjectName(u"horizontalLayout_19")
        self.passwd = QLabel(self.scrollAreaWidgetContents_2)
        self.passwd.setObjectName(u"passwd")
        self.passwd.setMinimumSize(QSize(80, 0))
        self.passwd.setMaximumSize(QSize(60, 16777215))
        self.passwd.setAlignment(Qt.AlignLeading|Qt.AlignLeft|Qt.AlignVCenter)

        self.horizontalLayout_19.addWidget(self.passwd)

        self.passwdEdit = QLineEdit(self.scrollAreaWidgetContents_2)
        self.passwdEdit.setObjectName(u"passwdEdit")

        self.horizontalLayout_19.addWidget(self.passwdEdit)


        self.verticalLayout_8.addLayout(self.horizontalLayout_19)

        self.verPicture = QLabel(self.scrollAreaWidgetContents_2)
        self.verPicture.setObjectName(u"verPicture")
        self.verPicture.setMinimumSize(QSize(0, 0))
        self.verPicture.setMaximumSize(QSize(16777215, 100))

        self.verticalLayout_8.addWidget(self.verPicture)

        self.horizontalLayout_7 = QHBoxLayout()
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.verLabel = QLabel(self.scrollAreaWidgetContents_2)
        self.verLabel.setObjectName(u"verLabel")
        self.verLabel.setMinimumSize(QSize(80, 0))

        self.horizontalLayout_7.addWidget(self.verLabel)

        self.verEdit = QLineEdit(self.scrollAreaWidgetContents_2)
        self.verEdit.setObjectName(u"verEdit")

        self.horizontalLayout_7.addWidget(self.verEdit)


        self.verticalLayout_8.addLayout(self.horizontalLayout_7)

        self.horizontalLayout_10 = QHBoxLayout()
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.gender_Male = QRadioButton(self.scrollAreaWidgetContents_2)
        self.sexGroup = QButtonGroup(LoginNew)
        self.sexGroup.setObjectName(u"sexGroup")
        self.sexGroup.addButton(self.gender_Male)
        self.gender_Male.setObjectName(u"gender_Male")
        self.gender_Male.setChecked(True)

        self.horizontalLayout_10.addWidget(self.gender_Male)

        self.gender_Female = QRadioButton(self.scrollAreaWidgetContents_2)
        self.sexGroup.addButton(self.gender_Female)
        self.gender_Female.setObjectName(u"gender_Female")

        self.horizontalLayout_10.addWidget(self.gender_Female)


        self.verticalLayout_8.addLayout(self.horizontalLayout_10)

        self.registerButton = QPushButton(self.scrollAreaWidgetContents_2)
        self.registerButton.setObjectName(u"registerButton")

        self.verticalLayout_8.addWidget(self.registerButton)

        self.scrollArea_2.setWidget(self.scrollAreaWidgetContents_2)

        self.horizontalLayout_4.addWidget(self.scrollArea_2)

        self.horizontalSpacer_4 = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.horizontalLayout_4.addItem(self.horizontalSpacer_4)


        self.verticalLayout_4.addLayout(self.horizontalLayout_4)

        self.tabWidget.addTab(self.tab_2, "")
        self.tab_3 = QWidget()
        self.tab_3.setObjectName(u"tab_3")
        self.horizontalLayout_8 = QHBoxLayout(self.tab_3)
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.horizontalSpacer_5 = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.horizontalLayout_8.addItem(self.horizontalSpacer_5)

        self.verticalLayout_6 = QVBoxLayout()
        self.verticalLayout_6.setObjectName(u"verticalLayout_6")
        self.scrollArea = SmoothScrollArea(self.tab_3)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 390, 537))
        self.verticalLayout_7 = QVBoxLayout(self.scrollAreaWidgetContents)
        self.verticalLayout_7.setObjectName(u"verticalLayout_7")
        self.label_7 = QLabel(self.scrollAreaWidgetContents)
        self.label_7.setObjectName(u"label_7")

        self.verticalLayout_7.addWidget(self.label_7)

        self.label_8 = QLabel(self.scrollAreaWidgetContents)
        self.label_8.setObjectName(u"label_8")

        self.verticalLayout_7.addWidget(self.label_8)

        self.commandLinkButton = QCommandLinkButton(self.scrollAreaWidgetContents)
        self.commandLinkButton.setObjectName(u"commandLinkButton")

        self.verticalLayout_7.addWidget(self.commandLinkButton)

        self.commandLinkButton2 = QCommandLinkButton(self.scrollAreaWidgetContents)
        self.commandLinkButton2.setObjectName(u"commandLinkButton2")

        self.verticalLayout_7.addWidget(self.commandLinkButton2)

        self.line = QFrame(self.scrollAreaWidgetContents)
        self.line.setObjectName(u"line")
        self.line.setFrameShape(QFrame.HLine)
        self.line.setFrameShadow(QFrame.Sunken)

        self.verticalLayout_7.addWidget(self.line)

        self.label_2 = QLabel(self.scrollAreaWidgetContents)
        self.label_2.setObjectName(u"label_2")

        self.verticalLayout_7.addWidget(self.label_2)

        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.label_3 = QLabel(self.scrollAreaWidgetContents)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout_9.addWidget(self.label_3)

        self.verfyEdit = QLineEdit(self.scrollAreaWidgetContents)
        self.verfyEdit.setObjectName(u"verfyEdit")

        self.horizontalLayout_9.addWidget(self.verfyEdit)


        self.verticalLayout_7.addLayout(self.horizontalLayout_9)

        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")
        self.label_9 = QLabel(self.scrollAreaWidgetContents)
        self.label_9.setObjectName(u"label_9")

        self.horizontalLayout_11.addWidget(self.label_9)

        self.verfyPsEdit = QLineEdit(self.scrollAreaWidgetContents)
        self.verfyPsEdit.setObjectName(u"verfyPsEdit")

        self.horizontalLayout_11.addWidget(self.verfyPsEdit)


        self.verticalLayout_7.addLayout(self.horizontalLayout_11)

        self.verfyButton = QPushButton(self.scrollAreaWidgetContents)
        self.verfyButton.setObjectName(u"verfyButton")

        self.verticalLayout_7.addWidget(self.verfyButton)

        self.verticalSpacer_5 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Minimum)

        self.verticalLayout_7.addItem(self.verticalSpacer_5)

        self.line_2 = QFrame(self.scrollAreaWidgetContents)
        self.line_2.setObjectName(u"line_2")
        self.line_2.setFrameShape(QFrame.HLine)
        self.line_2.setFrameShadow(QFrame.Sunken)

        self.verticalLayout_7.addWidget(self.line_2)

        self.label_4 = QLabel(self.scrollAreaWidgetContents)
        self.label_4.setObjectName(u"label_4")

        self.verticalLayout_7.addWidget(self.label_4)

        self.horizontalLayout_12 = QHBoxLayout()
        self.horizontalLayout_12.setObjectName(u"horizontalLayout_12")
        self.label_10 = QLabel(self.scrollAreaWidgetContents)
        self.label_10.setObjectName(u"label_10")

        self.horizontalLayout_12.addWidget(self.label_10)

        self.resetEdit = QLineEdit(self.scrollAreaWidgetContents)
        self.resetEdit.setObjectName(u"resetEdit")

        self.horizontalLayout_12.addWidget(self.resetEdit)


        self.verticalLayout_7.addLayout(self.horizontalLayout_12)

        self.resetButton = QPushButton(self.scrollAreaWidgetContents)
        self.resetButton.setObjectName(u"resetButton")

        self.verticalLayout_7.addWidget(self.resetButton)

        self.verticalSpacer_6 = QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Minimum)

        self.verticalLayout_7.addItem(self.verticalSpacer_6)

        self.line_3 = QFrame(self.scrollAreaWidgetContents)
        self.line_3.setObjectName(u"line_3")
        self.line_3.setFrameShape(QFrame.HLine)
        self.line_3.setFrameShadow(QFrame.Sunken)

        self.verticalLayout_7.addWidget(self.line_3)

        self.label_11 = QLabel(self.scrollAreaWidgetContents)
        self.label_11.setObjectName(u"label_11")

        self.verticalLayout_7.addWidget(self.label_11)

        self.horizontalLayout_13 = QHBoxLayout()
        self.horizontalLayout_13.setObjectName(u"horizontalLayout_13")
        self.label_12 = QLabel(self.scrollAreaWidgetContents)
        self.label_12.setObjectName(u"label_12")

        self.horizontalLayout_13.addWidget(self.label_12)

        self.sendEdit = QLineEdit(self.scrollAreaWidgetContents)
        self.sendEdit.setObjectName(u"sendEdit")

        self.horizontalLayout_13.addWidget(self.sendEdit)


        self.verticalLayout_7.addLayout(self.horizontalLayout_13)

        self.sendButton = QPushButton(self.scrollAreaWidgetContents)
        self.sendButton.setObjectName(u"sendButton")

        self.verticalLayout_7.addWidget(self.sendButton)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents)

        self.verticalLayout_6.addWidget(self.scrollArea)


        self.horizontalLayout_8.addLayout(self.verticalLayout_6)

        self.horizontalSpacer_6 = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.horizontalLayout_8.addItem(self.horizontalSpacer_6)

        self.tabWidget.addTab(self.tab_3, "")
        self.tab_4 = QWidget()
        self.tab_4.setObjectName(u"tab_4")
        self.verticalLayout_9 = QVBoxLayout(self.tab_4)
        self.verticalLayout_9.setSpacing(0)
        self.verticalLayout_9.setObjectName(u"verticalLayout_9")
        self.verticalLayout_9.setContentsMargins(0, 0, 0, 0)
        self.proxyHeader = QWidget(self.tab_4)
        self.proxyHeader.setObjectName(u"proxyHeader")
        self.proxyHeaderLayout = QHBoxLayout(self.proxyHeader)
        self.proxyHeaderLayout.setSpacing(8)
        self.proxyHeaderLayout.setObjectName(u"proxyHeaderLayout")
        self.proxyHeaderLayout.setContentsMargins(12, 0, 12, 0)
        self.proxyTitleLabel = QLabel(self.proxyHeader)
        self.proxyTitleLabel.setObjectName(u"proxyTitleLabel")

        self.proxyHeaderLayout.addWidget(self.proxyTitleLabel)

        self.proxyHeaderSpacer = QSpacerItem(40, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyHeaderLayout.addItem(self.proxyHeaderSpacer)

        self.cdnLinkButton = QCommandLinkButton(self.proxyHeader)
        self.cdnLinkButton.setObjectName(u"cdnLinkButton")

        self.proxyHeaderLayout.addWidget(self.cdnLinkButton)


        self.verticalLayout_9.addWidget(self.proxyHeader)

        self.proxyModeBox = QWidget(self.tab_4)
        self.proxyModeBox.setObjectName(u"proxyModeBox")
        self.proxyModeLayout = QVBoxLayout(self.proxyModeBox)
        self.proxyModeLayout.setSpacing(5)
        self.proxyModeLayout.setObjectName(u"proxyModeLayout")
        self.proxyModeLayout.setContentsMargins(12, 2, 12, 6)
        self.proxyModeRow = QHBoxLayout()
        self.proxyModeRow.setSpacing(6)
        self.proxyModeRow.setObjectName(u"proxyModeRow")
        self.proxy_0 = QRadioButton(self.proxyModeBox)
        self.radioProxyGroup = QButtonGroup(LoginNew)
        self.radioProxyGroup.setObjectName(u"radioProxyGroup")
        self.radioProxyGroup.addButton(self.proxy_0)
        self.proxy_0.setObjectName(u"proxy_0")

        self.proxyModeRow.addWidget(self.proxy_0)

        self.proxy_1 = QRadioButton(self.proxyModeBox)
        self.radioProxyGroup.addButton(self.proxy_1)
        self.proxy_1.setObjectName(u"proxy_1")

        self.proxyModeRow.addWidget(self.proxy_1)

        self.proxy_2 = QRadioButton(self.proxyModeBox)
        self.radioProxyGroup.addButton(self.proxy_2)
        self.proxy_2.setObjectName(u"proxy_2")

        self.proxyModeRow.addWidget(self.proxy_2)

        self.proxy_3 = QRadioButton(self.proxyModeBox)
        self.radioProxyGroup.addButton(self.proxy_3)
        self.proxy_3.setObjectName(u"proxy_3")

        self.proxyModeRow.addWidget(self.proxy_3)

        self.proxyModeSpacer = QSpacerItem(20, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyModeRow.addItem(self.proxyModeSpacer)


        self.proxyModeLayout.addLayout(self.proxyModeRow)

        self.proxyAddrRow = QHBoxLayout()
        self.proxyAddrRow.setSpacing(6)
        self.proxyAddrRow.setObjectName(u"proxyAddrRow")
        self.label_13 = QLabel(self.proxyModeBox)
        self.label_13.setObjectName(u"label_13")

        self.proxyAddrRow.addWidget(self.label_13)

        self.httpLine = QLineEdit(self.proxyModeBox)
        self.httpLine.setObjectName(u"httpLine")

        self.proxyAddrRow.addWidget(self.httpLine)

        self.sockEdit = QLineEdit(self.proxyModeBox)
        self.sockEdit.setObjectName(u"sockEdit")

        self.proxyAddrRow.addWidget(self.sockEdit)

        self.proxyLabel = QLabel(self.proxyModeBox)
        self.proxyLabel.setObjectName(u"proxyLabel")

        self.proxyAddrRow.addWidget(self.proxyLabel)

        self.checkLabel = QLabel(self.proxyModeBox)
        self.checkLabel.setObjectName(u"checkLabel")
        self.checkLabel.setStyleSheet(u"color:rgb(255, 0, 0)")

        self.proxyAddrRow.addWidget(self.checkLabel)

        self.proxyHint = QLabel(self.proxyModeBox)
        self.proxyHint.setObjectName(u"proxyHint")

        self.proxyAddrRow.addWidget(self.proxyHint)


        self.proxyModeLayout.addLayout(self.proxyAddrRow)


        self.verticalLayout_9.addWidget(self.proxyModeBox)

        self.speedBox = QWidget(self.tab_4)
        self.speedBox.setObjectName(u"speedBox")
        self.speedLayout = QVBoxLayout(self.speedBox)
        self.speedLayout.setSpacing(4)
        self.speedLayout.setObjectName(u"speedLayout")
        self.speedLayout.setContentsMargins(12, 2, 12, 4)
        self.speedCapRow = QHBoxLayout()
        self.speedCapRow.setSpacing(6)
        self.speedCapRow.setObjectName(u"speedCapRow")
        self.speedCapLabel = QLabel(self.speedBox)
        self.speedCapLabel.setObjectName(u"speedCapLabel")

        self.speedCapRow.addWidget(self.speedCapLabel)

        self.speedCapSpacer = QSpacerItem(40, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.speedCapRow.addItem(self.speedCapSpacer)

        self.speedUnitLabel = QLabel(self.speedBox)
        self.speedUnitLabel.setObjectName(u"speedUnitLabel")

        self.speedCapRow.addWidget(self.speedUnitLabel)


        self.speedLayout.addLayout(self.speedCapRow)

        self.speedBody = QHBoxLayout()
        self.speedBody.setSpacing(8)
        self.speedBody.setObjectName(u"speedBody")
        self.testSpeedButton = QPushButton(self.speedBox)
        self.testSpeedButton.setObjectName(u"testSpeedButton")
        self.testSpeedButton.setMinimumSize(QSize(46, 0))
        self.testSpeedButton.setMaximumSize(QSize(46, 16777215))

        self.speedBody.addWidget(self.testSpeedButton)

        self.speedGrid = QGridLayout()
        self.speedGrid.setObjectName(u"speedGrid")
        self.speedGrid.setHorizontalSpacing(4)
        self.speedGrid.setVerticalSpacing(3)
        self.chipApi1 = QWidget(self.speedBox)
        self.chipApi1.setObjectName(u"chipApi1")
        self.chipApi1Layout = QHBoxLayout(self.chipApi1)
        self.chipApi1Layout.setSpacing(2)
        self.chipApi1Layout.setObjectName(u"chipApi1Layout")
        self.chipApi1Layout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_1 = QRadioButton(self.chipApi1)
        self.radioApiGroup = QButtonGroup(LoginNew)
        self.radioApiGroup.setObjectName(u"radioApiGroup")
        self.radioApiGroup.addButton(self.radioButton_1)
        self.radioButton_1.setObjectName(u"radioButton_1")

        self.chipApi1Layout.addWidget(self.radioButton_1)

        self.label_api_1 = QLabel(self.chipApi1)
        self.label_api_1.setObjectName(u"label_api_1")

        self.chipApi1Layout.addWidget(self.label_api_1)


        self.speedGrid.addWidget(self.chipApi1, 0, 0, 1, 1)

        self.chipApi2 = QWidget(self.speedBox)
        self.chipApi2.setObjectName(u"chipApi2")
        self.chipApi2Layout = QHBoxLayout(self.chipApi2)
        self.chipApi2Layout.setSpacing(2)
        self.chipApi2Layout.setObjectName(u"chipApi2Layout")
        self.chipApi2Layout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_2 = QRadioButton(self.chipApi2)
        self.radioApiGroup.addButton(self.radioButton_2)
        self.radioButton_2.setObjectName(u"radioButton_2")

        self.chipApi2Layout.addWidget(self.radioButton_2)

        self.label_api_2 = QLabel(self.chipApi2)
        self.label_api_2.setObjectName(u"label_api_2")

        self.chipApi2Layout.addWidget(self.label_api_2)


        self.speedGrid.addWidget(self.chipApi2, 0, 1, 1, 1)

        self.chipApi3 = QWidget(self.speedBox)
        self.chipApi3.setObjectName(u"chipApi3")
        self.chipApi3Layout = QHBoxLayout(self.chipApi3)
        self.chipApi3Layout.setSpacing(2)
        self.chipApi3Layout.setObjectName(u"chipApi3Layout")
        self.chipApi3Layout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_3 = QRadioButton(self.chipApi3)
        self.radioApiGroup.addButton(self.radioButton_3)
        self.radioButton_3.setObjectName(u"radioButton_3")

        self.chipApi3Layout.addWidget(self.radioButton_3)

        self.label_api_3 = QLabel(self.chipApi3)
        self.label_api_3.setObjectName(u"label_api_3")

        self.chipApi3Layout.addWidget(self.label_api_3)


        self.speedGrid.addWidget(self.chipApi3, 0, 2, 1, 1)

        self.chipApi4 = QWidget(self.speedBox)
        self.chipApi4.setObjectName(u"chipApi4")
        self.chipApi4Layout = QHBoxLayout(self.chipApi4)
        self.chipApi4Layout.setSpacing(2)
        self.chipApi4Layout.setObjectName(u"chipApi4Layout")
        self.chipApi4Layout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_4 = QRadioButton(self.chipApi4)
        self.radioApiGroup.addButton(self.radioButton_4)
        self.radioButton_4.setObjectName(u"radioButton_4")

        self.chipApi4Layout.addWidget(self.radioButton_4)

        self.label_api_4 = QLabel(self.chipApi4)
        self.label_api_4.setObjectName(u"label_api_4")

        self.chipApi4Layout.addWidget(self.label_api_4)


        self.speedGrid.addWidget(self.chipApi4, 0, 3, 1, 1)

        self.chipApi5 = QWidget(self.speedBox)
        self.chipApi5.setObjectName(u"chipApi5")
        self.chipApi5Layout = QHBoxLayout(self.chipApi5)
        self.chipApi5Layout.setSpacing(2)
        self.chipApi5Layout.setObjectName(u"chipApi5Layout")
        self.chipApi5Layout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_5 = QRadioButton(self.chipApi5)
        self.radioApiGroup.addButton(self.radioButton_5)
        self.radioButton_5.setObjectName(u"radioButton_5")

        self.chipApi5Layout.addWidget(self.radioButton_5)

        self.label_api_5 = QLabel(self.chipApi5)
        self.label_api_5.setObjectName(u"label_api_5")

        self.chipApi5Layout.addWidget(self.label_api_5)


        self.speedGrid.addWidget(self.chipApi5, 0, 4, 1, 1)

        self.chipApi6 = QWidget(self.speedBox)
        self.chipApi6.setObjectName(u"chipApi6")
        self.chipApi6Layout = QHBoxLayout(self.chipApi6)
        self.chipApi6Layout.setSpacing(2)
        self.chipApi6Layout.setObjectName(u"chipApi6Layout")
        self.chipApi6Layout.setContentsMargins(0, 0, 0, 0)
        self.radioButton_6 = QRadioButton(self.chipApi6)
        self.radioApiGroup.addButton(self.radioButton_6)
        self.radioButton_6.setObjectName(u"radioButton_6")

        self.chipApi6Layout.addWidget(self.radioButton_6)

        self.label_api_6 = QLabel(self.chipApi6)
        self.label_api_6.setObjectName(u"label_api_6")

        self.chipApi6Layout.addWidget(self.label_api_6)


        self.speedGrid.addWidget(self.chipApi6, 0, 5, 1, 1)

        self.chipImg1 = QWidget(self.speedBox)
        self.chipImg1.setObjectName(u"chipImg1")
        self.chipImg1Layout = QHBoxLayout(self.chipImg1)
        self.chipImg1Layout.setSpacing(2)
        self.chipImg1Layout.setObjectName(u"chipImg1Layout")
        self.chipImg1Layout.setContentsMargins(0, 0, 0, 0)
        self.radio_img_1 = QRadioButton(self.chipImg1)
        self.radioImgGroup = QButtonGroup(LoginNew)
        self.radioImgGroup.setObjectName(u"radioImgGroup")
        self.radioImgGroup.addButton(self.radio_img_1)
        self.radio_img_1.setObjectName(u"radio_img_1")

        self.chipImg1Layout.addWidget(self.radio_img_1)

        self.label_img_1 = QLabel(self.chipImg1)
        self.label_img_1.setObjectName(u"label_img_1")

        self.chipImg1Layout.addWidget(self.label_img_1)


        self.speedGrid.addWidget(self.chipImg1, 1, 0, 1, 1)

        self.chipImg2 = QWidget(self.speedBox)
        self.chipImg2.setObjectName(u"chipImg2")
        self.chipImg2Layout = QHBoxLayout(self.chipImg2)
        self.chipImg2Layout.setSpacing(2)
        self.chipImg2Layout.setObjectName(u"chipImg2Layout")
        self.chipImg2Layout.setContentsMargins(0, 0, 0, 0)
        self.radio_img_2 = QRadioButton(self.chipImg2)
        self.radioImgGroup.addButton(self.radio_img_2)
        self.radio_img_2.setObjectName(u"radio_img_2")

        self.chipImg2Layout.addWidget(self.radio_img_2)

        self.label_img_2 = QLabel(self.chipImg2)
        self.label_img_2.setObjectName(u"label_img_2")

        self.chipImg2Layout.addWidget(self.label_img_2)


        self.speedGrid.addWidget(self.chipImg2, 1, 1, 1, 1)

        self.chipImg3 = QWidget(self.speedBox)
        self.chipImg3.setObjectName(u"chipImg3")
        self.chipImg3Layout = QHBoxLayout(self.chipImg3)
        self.chipImg3Layout.setSpacing(2)
        self.chipImg3Layout.setObjectName(u"chipImg3Layout")
        self.chipImg3Layout.setContentsMargins(0, 0, 0, 0)
        self.radio_img_3 = QRadioButton(self.chipImg3)
        self.radioImgGroup.addButton(self.radio_img_3)
        self.radio_img_3.setObjectName(u"radio_img_3")

        self.chipImg3Layout.addWidget(self.radio_img_3)

        self.label_img_3 = QLabel(self.chipImg3)
        self.label_img_3.setObjectName(u"label_img_3")

        self.chipImg3Layout.addWidget(self.label_img_3)


        self.speedGrid.addWidget(self.chipImg3, 1, 2, 1, 1)

        self.chipImg4 = QWidget(self.speedBox)
        self.chipImg4.setObjectName(u"chipImg4")
        self.chipImg4Layout = QHBoxLayout(self.chipImg4)
        self.chipImg4Layout.setSpacing(2)
        self.chipImg4Layout.setObjectName(u"chipImg4Layout")
        self.chipImg4Layout.setContentsMargins(0, 0, 0, 0)
        self.radio_img_4 = QRadioButton(self.chipImg4)
        self.radioImgGroup.addButton(self.radio_img_4)
        self.radio_img_4.setObjectName(u"radio_img_4")

        self.chipImg4Layout.addWidget(self.radio_img_4)

        self.label_img_4 = QLabel(self.chipImg4)
        self.label_img_4.setObjectName(u"label_img_4")

        self.chipImg4Layout.addWidget(self.label_img_4)


        self.speedGrid.addWidget(self.chipImg4, 1, 3, 1, 1)

        self.chipImg5 = QWidget(self.speedBox)
        self.chipImg5.setObjectName(u"chipImg5")
        self.chipImg5Layout = QHBoxLayout(self.chipImg5)
        self.chipImg5Layout.setSpacing(2)
        self.chipImg5Layout.setObjectName(u"chipImg5Layout")
        self.chipImg5Layout.setContentsMargins(0, 0, 0, 0)
        self.radio_img_5 = QRadioButton(self.chipImg5)
        self.radioImgGroup.addButton(self.radio_img_5)
        self.radio_img_5.setObjectName(u"radio_img_5")

        self.chipImg5Layout.addWidget(self.radio_img_5)

        self.label_img_5 = QLabel(self.chipImg5)
        self.label_img_5.setObjectName(u"label_img_5")

        self.chipImg5Layout.addWidget(self.label_img_5)


        self.speedGrid.addWidget(self.chipImg5, 1, 4, 1, 1)

        self.chipImg6 = QWidget(self.speedBox)
        self.chipImg6.setObjectName(u"chipImg6")
        self.chipImg6Layout = QHBoxLayout(self.chipImg6)
        self.chipImg6Layout.setSpacing(2)
        self.chipImg6Layout.setObjectName(u"chipImg6Layout")
        self.chipImg6Layout.setContentsMargins(0, 0, 0, 0)
        self.radio_img_6 = QRadioButton(self.chipImg6)
        self.radioImgGroup.addButton(self.radio_img_6)
        self.radio_img_6.setObjectName(u"radio_img_6")

        self.chipImg6Layout.addWidget(self.radio_img_6)

        self.label_img_6 = QLabel(self.chipImg6)
        self.label_img_6.setObjectName(u"label_img_6")

        self.chipImg6Layout.addWidget(self.label_img_6)


        self.speedGrid.addWidget(self.chipImg6, 1, 5, 1, 1)


        self.speedBody.addLayout(self.speedGrid)


        self.speedLayout.addLayout(self.speedBody)


        self.verticalLayout_9.addWidget(self.speedBox)

        self.proxyListBox = QWidget(self.tab_4)
        self.proxyListBox.setObjectName(u"proxyListBox")
        self.proxyListLayout = QVBoxLayout(self.proxyListBox)
        self.proxyListLayout.setSpacing(0)
        self.proxyListLayout.setObjectName(u"proxyListLayout")
        self.proxyListLayout.setContentsMargins(0, 0, 0, 0)
        self.proxyListHead = QWidget(self.proxyListBox)
        self.proxyListHead.setObjectName(u"proxyListHead")
        self.proxyListHeadLayout = QHBoxLayout(self.proxyListHead)
        self.proxyListHeadLayout.setSpacing(6)
        self.proxyListHeadLayout.setObjectName(u"proxyListHeadLayout")
        self.proxyListHeadLayout.setContentsMargins(12, 0, 12, 0)
        self.proxyListTitle = QLabel(self.proxyListHead)
        self.proxyListTitle.setObjectName(u"proxyListTitle")

        self.proxyListHeadLayout.addWidget(self.proxyListTitle)

        self.proxyCountLabel = QLabel(self.proxyListHead)
        self.proxyCountLabel.setObjectName(u"proxyCountLabel")

        self.proxyListHeadLayout.addWidget(self.proxyCountLabel)

        self.proxyHeadSpacer = QSpacerItem(40, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyListHeadLayout.addItem(self.proxyHeadSpacer)

        self.proxySortButton = QPushButton(self.proxyListHead)
        self.proxySortButton.setObjectName(u"proxySortButton")

        self.proxyListHeadLayout.addWidget(self.proxySortButton)

        self.proxyDensityButton = QPushButton(self.proxyListHead)
        self.proxyDensityButton.setObjectName(u"proxyDensityButton")
        self.proxyDensityButton.setMaximumSize(QSize(34, 16777215))

        self.proxyListHeadLayout.addWidget(self.proxyDensityButton)


        self.proxyListLayout.addWidget(self.proxyListHead)

        self.proxyFilterBar = QWidget(self.proxyListBox)
        self.proxyFilterBar.setObjectName(u"proxyFilterBar")
        self.proxyFilterLayout = QHBoxLayout(self.proxyFilterBar)
        self.proxyFilterLayout.setSpacing(5)
        self.proxyFilterLayout.setObjectName(u"proxyFilterLayout")
        self.proxyFilterLayout.setContentsMargins(12, 0, 12, 0)
        self.proxyFilterAll = QPushButton(self.proxyFilterBar)
        self.proxyFilterGroup = QButtonGroup(LoginNew)
        self.proxyFilterGroup.setObjectName(u"proxyFilterGroup")
        self.proxyFilterGroup.addButton(self.proxyFilterAll)
        self.proxyFilterAll.setObjectName(u"proxyFilterAll")
        self.proxyFilterAll.setCheckable(True)
        self.proxyFilterAll.setChecked(True)

        self.proxyFilterLayout.addWidget(self.proxyFilterAll)

        self.proxyFilterProxy = QPushButton(self.proxyFilterBar)
        self.proxyFilterGroup.addButton(self.proxyFilterProxy)
        self.proxyFilterProxy.setObjectName(u"proxyFilterProxy")
        self.proxyFilterProxy.setCheckable(True)

        self.proxyFilterLayout.addWidget(self.proxyFilterProxy)

        self.proxyFilterCf = QPushButton(self.proxyFilterBar)
        self.proxyFilterGroup.addButton(self.proxyFilterCf)
        self.proxyFilterCf.setObjectName(u"proxyFilterCf")
        self.proxyFilterCf.setCheckable(True)

        self.proxyFilterLayout.addWidget(self.proxyFilterCf)

        self.proxyFilterSpacer = QSpacerItem(40, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyFilterLayout.addItem(self.proxyFilterSpacer)

        self.proxyCutLabel = QLabel(self.proxyFilterBar)
        self.proxyCutLabel.setObjectName(u"proxyCutLabel")

        self.proxyFilterLayout.addWidget(self.proxyCutLabel)


        self.proxyListLayout.addWidget(self.proxyFilterBar)

        self.proxyColHead = QWidget(self.proxyListBox)
        self.proxyColHead.setObjectName(u"proxyColHead")
        self.proxyColHeadLayout = QHBoxLayout(self.proxyColHead)
        self.proxyColHeadLayout.setSpacing(8)
        self.proxyColHeadLayout.setObjectName(u"proxyColHeadLayout")
        self.proxyColHeadLayout.setContentsMargins(34, 0, 12, 0)
        self.colNameLabel = QLabel(self.proxyColHead)
        self.colNameLabel.setObjectName(u"colNameLabel")

        self.proxyColHeadLayout.addWidget(self.colNameLabel)

        self.colSpeedLabel = QLabel(self.proxyColHead)
        self.colSpeedLabel.setObjectName(u"colSpeedLabel")
        self.colSpeedLabel.setMinimumSize(QSize(86, 0))
        self.colSpeedLabel.setAlignment(Qt.AlignRight|Qt.AlignTrailing|Qt.AlignVCenter)

        self.proxyColHeadLayout.addWidget(self.colSpeedLabel)


        self.proxyListLayout.addWidget(self.proxyColHead)

        self.tableWidget = BaseTableWidget(self.proxyListBox)
        if (self.tableWidget.columnCount() < 1):
            self.tableWidget.setColumnCount(1)
        __qtablewidgetitem = QTableWidgetItem()
        self.tableWidget.setHorizontalHeaderItem(0, __qtablewidgetitem)
        self.tableWidget.setObjectName(u"tableWidget")

        self.proxyListLayout.addWidget(self.tableWidget)


        self.verticalLayout_9.addWidget(self.proxyListBox)

        self.proxyAdvPanel = QWidget(self.tab_4)
        self.proxyAdvPanel.setObjectName(u"proxyAdvPanel")
        self.proxyAdvPanel.setVisible(False)
        self.proxyAdvLayout = QVBoxLayout(self.proxyAdvPanel)
        self.proxyAdvLayout.setSpacing(4)
        self.proxyAdvLayout.setObjectName(u"proxyAdvLayout")
        self.proxyAdvLayout.setContentsMargins(12, 4, 12, 6)
        self.proxyTimeoutRow = QHBoxLayout()
        self.proxyTimeoutRow.setSpacing(6)
        self.proxyTimeoutRow.setObjectName(u"proxyTimeoutRow")
        self.label_15 = QLabel(self.proxyAdvPanel)
        self.label_15.setObjectName(u"label_15")

        self.proxyTimeoutRow.addWidget(self.label_15)

        self.apiTimeout = WheelComboBox(self.proxyAdvPanel)
        self.apiTimeout.addItem("")
        self.apiTimeout.addItem("")
        self.apiTimeout.addItem("")
        self.apiTimeout.setObjectName(u"apiTimeout")

        self.proxyTimeoutRow.addWidget(self.apiTimeout)

        self.label_16 = QLabel(self.proxyAdvPanel)
        self.label_16.setObjectName(u"label_16")

        self.proxyTimeoutRow.addWidget(self.label_16)

        self.imgTimeout = WheelComboBox(self.proxyAdvPanel)
        self.imgTimeout.addItem("")
        self.imgTimeout.addItem("")
        self.imgTimeout.addItem("")
        self.imgTimeout.addItem("")
        self.imgTimeout.addItem("")
        self.imgTimeout.setObjectName(u"imgTimeout")

        self.proxyTimeoutRow.addWidget(self.imgTimeout)

        self.proxyTimeoutSpacer = QSpacerItem(20, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyTimeoutRow.addItem(self.proxyTimeoutSpacer)


        self.proxyAdvLayout.addLayout(self.proxyTimeoutRow)

        self.proxyDohRow = QHBoxLayout()
        self.proxyDohRow.setSpacing(6)
        self.proxyDohRow.setObjectName(u"proxyDohRow")
        self.label_17 = QLabel(self.proxyAdvPanel)
        self.label_17.setObjectName(u"label_17")

        self.proxyDohRow.addWidget(self.label_17)

        self.dohLine = TipLineEdit(self.proxyAdvPanel)
        self.dohLine.setObjectName(u"dohLine")

        self.proxyDohRow.addWidget(self.dohLine)

        self.dohTool = QToolButton(self.proxyAdvPanel)
        self.dohTool.setObjectName(u"dohTool")

        self.proxyDohRow.addWidget(self.dohTool)


        self.proxyAdvLayout.addLayout(self.proxyDohRow)

        self.proxyTlsRow = QHBoxLayout()
        self.proxyTlsRow.setSpacing(10)
        self.proxyTlsRow.setObjectName(u"proxyTlsRow")
        self.echBox = QCheckBox(self.proxyAdvPanel)
        self.echBox.setObjectName(u"echBox")
        self.echBox.setChecked(True)

        self.proxyTlsRow.addWidget(self.echBox)

        self.http3Box = QCheckBox(self.proxyAdvPanel)
        self.http3Box.setObjectName(u"http3Box")

        self.proxyTlsRow.addWidget(self.http3Box)

        self.proxyTlsSpacer = QSpacerItem(20, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyTlsRow.addItem(self.proxyTlsSpacer)


        self.proxyAdvLayout.addLayout(self.proxyTlsRow)

        self.proxyRegionRow = QHBoxLayout()
        self.proxyRegionRow.setSpacing(6)
        self.proxyRegionRow.setObjectName(u"proxyRegionRow")
        self.label_26 = QLabel(self.proxyAdvPanel)
        self.label_26.setObjectName(u"label_26")

        self.proxyRegionRow.addWidget(self.label_26)

        self.proxyIpEdit = TipLineEdit(self.proxyAdvPanel)
        self.proxyIpEdit.setObjectName(u"proxyIpEdit")
        self.proxyIpEdit.setMaximumSize(QSize(110, 16777215))

        self.proxyRegionRow.addWidget(self.proxyIpEdit)

        self.proxyIpLabel = QLabel(self.proxyAdvPanel)
        self.proxyIpLabel.setObjectName(u"proxyIpLabel")

        self.proxyRegionRow.addWidget(self.proxyIpLabel)

        self.proxyRegionSpacer = QSpacerItem(20, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)

        self.proxyRegionRow.addItem(self.proxyRegionSpacer)


        self.proxyAdvLayout.addLayout(self.proxyRegionRow)

        self.proxyIpListRow = QHBoxLayout()
        self.proxyIpListRow.setSpacing(6)
        self.proxyIpListRow.setObjectName(u"proxyIpListRow")
        self.label_22 = QLabel(self.proxyAdvPanel)
        self.label_22.setObjectName(u"label_22")

        self.proxyIpListRow.addWidget(self.label_22)

        self.ipListEdit = QLineEdit(self.proxyAdvPanel)
        self.ipListEdit.setObjectName(u"ipListEdit")

        self.proxyIpListRow.addWidget(self.ipListEdit)


        self.proxyAdvLayout.addLayout(self.proxyIpListRow)

        self.label_25 = QLabel(self.proxyAdvPanel)
        self.label_25.setObjectName(u"label_25")

        self.proxyAdvLayout.addWidget(self.label_25)


        self.verticalLayout_9.addWidget(self.proxyAdvPanel)

        self.proxyFoot = QWidget(self.tab_4)
        self.proxyFoot.setObjectName(u"proxyFoot")
        self.proxyFootLayout = QHBoxLayout(self.proxyFoot)
        self.proxyFootLayout.setSpacing(8)
        self.proxyFootLayout.setObjectName(u"proxyFootLayout")
        self.proxyFootLayout.setContentsMargins(12, 4, 12, 6)
        self.proxyStatusLabel = QLabel(self.proxyFoot)
        self.proxyStatusLabel.setObjectName(u"proxyStatusLabel")

        self.proxyFootLayout.addWidget(self.proxyStatusLabel)

        self.proxyAdvButton = QPushButton(self.proxyFoot)
        self.proxyAdvButton.setObjectName(u"proxyAdvButton")

        self.proxyFootLayout.addWidget(self.proxyAdvButton)

        self.testIpButton = QPushButton(self.proxyFoot)
        self.testIpButton.setObjectName(u"testIpButton")

        self.proxyFootLayout.addWidget(self.testIpButton)


        self.verticalLayout_9.addWidget(self.proxyFoot)

        self.tabWidget.addTab(self.tab_4, "")

        self.horizontalLayout_3.addWidget(self.tabWidget)

        QWidget.setTabOrder(self.proxyIpEdit, self.ipListEdit)
        QWidget.setTabOrder(self.ipListEdit, self.passwdEdit_2)
        QWidget.setTabOrder(self.passwdEdit_2, self.saveBox)
        QWidget.setTabOrder(self.saveBox, self.autoBox)
        QWidget.setTabOrder(self.autoBox, self.autoSign)
        QWidget.setTabOrder(self.autoSign, self.loginButton)
        QWidget.setTabOrder(self.loginButton, self.scrollArea_2)
        QWidget.setTabOrder(self.scrollArea_2, self.userEdit)
        QWidget.setTabOrder(self.userEdit, self.nameEdit)
        QWidget.setTabOrder(self.nameEdit, self.passwdEdit)
        QWidget.setTabOrder(self.passwdEdit, self.verEdit)
        QWidget.setTabOrder(self.verEdit, self.gender_Male)
        QWidget.setTabOrder(self.gender_Male, self.gender_Female)
        QWidget.setTabOrder(self.gender_Female, self.registerButton)
        QWidget.setTabOrder(self.registerButton, self.scrollArea)
        QWidget.setTabOrder(self.scrollArea, self.commandLinkButton)
        QWidget.setTabOrder(self.commandLinkButton, self.commandLinkButton2)
        QWidget.setTabOrder(self.commandLinkButton2, self.verfyEdit)
        QWidget.setTabOrder(self.verfyEdit, self.verfyPsEdit)
        QWidget.setTabOrder(self.verfyPsEdit, self.verfyButton)
        QWidget.setTabOrder(self.verfyButton, self.resetEdit)
        QWidget.setTabOrder(self.resetEdit, self.resetButton)
        QWidget.setTabOrder(self.resetButton, self.sendEdit)
        QWidget.setTabOrder(self.sendEdit, self.sendButton)
        QWidget.setTabOrder(self.sendButton, self.proxy_0)
        QWidget.setTabOrder(self.proxy_0, self.proxy_1)
        QWidget.setTabOrder(self.proxy_1, self.httpLine)
        QWidget.setTabOrder(self.httpLine, self.proxy_2)
        QWidget.setTabOrder(self.proxy_2, self.sockEdit)
        QWidget.setTabOrder(self.sockEdit, self.proxy_3)
        QWidget.setTabOrder(self.proxy_3, self.apiTimeout)
        QWidget.setTabOrder(self.apiTimeout, self.imgTimeout)
        QWidget.setTabOrder(self.imgTimeout, self.http3Box)
        QWidget.setTabOrder(self.http3Box, self.echBox)
        QWidget.setTabOrder(self.echBox, self.dohLine)
        QWidget.setTabOrder(self.dohLine, self.dohTool)
        QWidget.setTabOrder(self.dohTool, self.testSpeedButton)
        QWidget.setTabOrder(self.testSpeedButton, self.radioButton_3)
        QWidget.setTabOrder(self.radioButton_3, self.radio_img_4)
        QWidget.setTabOrder(self.radio_img_4, self.radio_img_6)
        QWidget.setTabOrder(self.radio_img_6, self.radio_img_2)
        QWidget.setTabOrder(self.radio_img_2, self.radioButton_4)
        QWidget.setTabOrder(self.radioButton_4, self.radioButton_6)
        QWidget.setTabOrder(self.radioButton_6, self.radio_img_1)
        QWidget.setTabOrder(self.radio_img_1, self.radioButton_2)
        QWidget.setTabOrder(self.radioButton_2, self.radioButton_1)
        QWidget.setTabOrder(self.radioButton_1, self.radio_img_3)
        QWidget.setTabOrder(self.radio_img_3, self.radioButton_5)
        QWidget.setTabOrder(self.radioButton_5, self.radio_img_5)
        QWidget.setTabOrder(self.radio_img_5, self.testIpButton)
        QWidget.setTabOrder(self.testIpButton, self.tabWidget)
        QWidget.setTabOrder(self.tabWidget, self.userEdit_2)
        QWidget.setTabOrder(self.userEdit_2, self.tableWidget)
        QWidget.setTabOrder(self.tableWidget, self.cdnLinkButton)

        self.retranslateUi(LoginNew)

        self.tabWidget.setCurrentIndex(3)


        QMetaObject.connectSlotsByName(LoginNew)
    # setupUi

    def retranslateUi(self, LoginNew):
        LoginNew.setWindowTitle(QCoreApplication.translate("LoginNew", u"\u767b\u5f55", None))
        self.label_5.setText(QCoreApplication.translate("LoginNew", u"\u7528\u6237\u540d", None))
        self.label_6.setText(QCoreApplication.translate("LoginNew", u"\u5bc6\u7801", None))
        self.saveBox.setText(QCoreApplication.translate("LoginNew", u"\u4fdd\u5b58\u5bc6\u7801", None))
        self.autoBox.setText(QCoreApplication.translate("LoginNew", u"\u81ea\u52a8\u767b\u5f55", None))
        self.autoSign.setText(QCoreApplication.translate("LoginNew", u"\u81ea\u52a8\u6253\u5361", None))
        self.loginButton.setText(QCoreApplication.translate("LoginNew", u"\u767b\u5f55", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), QCoreApplication.translate("LoginNew", u"\u767b\u5f55", None))
        self.label.setText(QCoreApplication.translate("LoginNew", u"\u5982\u679c\u65e0\u6cd5\u4f7f\u7528\uff0c\u8bf7\u81ea\u884c\u7f51\u9875\u6ce8\u518c", None))
        self.user.setText(QCoreApplication.translate("LoginNew", u"\u90ae\u7bb1\uff1a", None))
        self.name.setText(QCoreApplication.translate("LoginNew", u"\u7528\u6237\u540d\uff1a", None))
        self.passwd.setText(QCoreApplication.translate("LoginNew", u"\u5bc6\u7801\uff1a", None))
        self.verPicture.setText(QCoreApplication.translate("LoginNew", u"\u9a8c\u8bc1\u7801\u3002\u3002\u3002", None))
        self.verLabel.setText(QCoreApplication.translate("LoginNew", u"\u9a8c\u8bc1\u7801", None))
        self.gender_Male.setText(QCoreApplication.translate("LoginNew", u"\u7537", None))
        self.gender_Female.setText(QCoreApplication.translate("LoginNew", u"\u5973", None))
        self.registerButton.setText(QCoreApplication.translate("LoginNew", u"\u6ce8\u518c", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_2), QCoreApplication.translate("LoginNew", u"\u6ce8\u518c", None))
        self.label_7.setText(QCoreApplication.translate("LoginNew", u"\u5982\u679c\u4f60\u7684\u90ae\u4ef6\u4e00\u76f4\u65e0\u6cd5\u63a5\u53d7\u5230\u9a8c\u8bc1\u8fde\u63a5", None))
        self.label_8.setText(QCoreApplication.translate("LoginNew", u"\u8bf7\u524d\u5f80\u5b98\u65b9Discord\u9891\u9053-\u672a\u6536\u5230\u9a8c\u8bc1\u4fe1\u534f\u52a9\u533a", None))
        self.commandLinkButton.setText(QCoreApplication.translate("LoginNew", u"\u5b98\u65b9Discord", None))
        self.commandLinkButton2.setText(QCoreApplication.translate("LoginNew", u"\u5b98\u65b9Telegram", None))
        self.label_2.setText(QCoreApplication.translate("LoginNew", u"\u91cd\u65b0\u53d1\u9001\u90ae\u7bb1\u9a8c\u8bc1", None))
        self.label_3.setText(QCoreApplication.translate("LoginNew", u"\u7528\u6237\u540d\uff1a", None))
        self.label_9.setText(QCoreApplication.translate("LoginNew", u"\u5bc6    \u7801\uff1a", None))
        self.verfyButton.setText(QCoreApplication.translate("LoginNew", u"\u53d1\u9001", None))
        self.label_4.setText(QCoreApplication.translate("LoginNew", u"\u5fd8\u8bb0\u7528\u6237\u540d\u6216\u5bc6\u7801", None))
        self.label_10.setText(QCoreApplication.translate("LoginNew", u"\u90ae\u7bb1\uff1a", None))
        self.resetButton.setText(QCoreApplication.translate("LoginNew", u"\u53d1\u9001", None))
        self.label_11.setText(QCoreApplication.translate("LoginNew", u"\u8d26\u53f7\u9a8c\u8bc1\uff08\u5982\u679c\u4f60\u65e0\u6cd5\u6253\u5f00\u90ae\u7bb1\u91cc\u7684\u9a8c\u8bc1\u5730\u5740\uff0c\u53ef\u4ee5\u590d\u5236\u5230\u6b64\u5904\u9a8c\u8bc1\uff09", None))
        self.label_12.setText(QCoreApplication.translate("LoginNew", u"\u5730\u5740\uff1a", None))
        self.sendButton.setText(QCoreApplication.translate("LoginNew", u"\u53d1\u9001", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_3), QCoreApplication.translate("LoginNew", u"\u9a8c\u8bc1", None))
        self.proxyTitleLabel.setText(QCoreApplication.translate("LoginNew", u"\u5206\u6d41\u8bbe\u7f6e", None))
        self.cdnLinkButton.setText(QCoreApplication.translate("LoginNew", u"\u8bf4\u660e", None))
        self.proxy_0.setText(QCoreApplication.translate("LoginNew", u"\u65e0\u4ee3\u7406", None))
        self.proxy_1.setText(QCoreApplication.translate("LoginNew", u"HTTP", None))
        self.proxy_2.setText(QCoreApplication.translate("LoginNew", u"Socks5", None))
        self.proxy_3.setText(QCoreApplication.translate("LoginNew", u"\u7cfb\u7edf", None))
        self.label_13.setText(QCoreApplication.translate("LoginNew", u"\u4ee3\u7406\u5730\u5740", None))
#if QT_CONFIG(tooltip)
        self.httpLine.setToolTip(QCoreApplication.translate("LoginNew", u"http://127.0.0.1:10809", None))
#endif // QT_CONFIG(tooltip)
        self.httpLine.setPlaceholderText("")
#if QT_CONFIG(tooltip)
        self.sockEdit.setToolTip(QCoreApplication.translate("LoginNew", u"127.0.0.1:10808", None))
#endif // QT_CONFIG(tooltip)
        self.sockEdit.setPlaceholderText("")
        self.proxyLabel.setText("")
        self.checkLabel.setText(QCoreApplication.translate("LoginNew", u"\u672a\u68c0\u6d4b\u5230\u7cfb\u7edf\u4ee3\u7406", None))
        self.proxyHint.setText(QCoreApplication.translate("LoginNew", u"\u672a\u542f\u7528\u4ee3\u7406", None))
        self.speedCapLabel.setText(QCoreApplication.translate("LoginNew", u"\u7ebf\u8def\u6d4b\u901f", None))
        self.speedUnitLabel.setText(QCoreApplication.translate("LoginNew", u"\u5ef6\u8fdf / \u4e0b\u8f7d \u00b7 ms", None))
        self.testSpeedButton.setText(QCoreApplication.translate("LoginNew", u"\u6d4b\u901f", None))
        self.radioButton_1.setText(QCoreApplication.translate("LoginNew", u"1", None))
        self.label_api_1.setText("")
        self.radioButton_2.setText(QCoreApplication.translate("LoginNew", u"2", None))
        self.label_api_2.setText("")
        self.radioButton_3.setText(QCoreApplication.translate("LoginNew", u"3", None))
        self.label_api_3.setText("")
        self.radioButton_4.setText(QCoreApplication.translate("LoginNew", u"4", None))
        self.label_api_4.setText("")
        self.radioButton_5.setText(QCoreApplication.translate("LoginNew", u"IP", None))
        self.label_api_5.setText("")
        self.radioButton_6.setText(QCoreApplication.translate("LoginNew", u"6", None))
        self.label_api_6.setText("")
        self.radio_img_1.setText(QCoreApplication.translate("LoginNew", u"1", None))
        self.label_img_1.setText("")
        self.radio_img_2.setText(QCoreApplication.translate("LoginNew", u"2", None))
        self.label_img_2.setText("")
        self.radio_img_3.setText(QCoreApplication.translate("LoginNew", u"3", None))
        self.label_img_3.setText("")
        self.radio_img_4.setText(QCoreApplication.translate("LoginNew", u"4", None))
        self.label_img_4.setText("")
        self.radio_img_5.setText(QCoreApplication.translate("LoginNew", u"IP", None))
        self.label_img_5.setText("")
        self.radio_img_6.setText(QCoreApplication.translate("LoginNew", u"6", None))
        self.label_img_6.setText("")
        self.proxyListTitle.setText(QCoreApplication.translate("LoginNew", u"\u8282\u70b9\u5217\u8868", None))
        self.proxyCountLabel.setText("")
        self.proxySortButton.setText(QCoreApplication.translate("LoginNew", u"\u667a\u80fd\u6392\u5e8f \u25be", None))
#if QT_CONFIG(tooltip)
        self.proxyDensityButton.setToolTip(QCoreApplication.translate("LoginNew", u"\u7d27\u51d1 / \u8212\u9002", None))
#endif // QT_CONFIG(tooltip)
        self.proxyDensityButton.setText(QCoreApplication.translate("LoginNew", u"\u2261", None))
        self.proxyFilterAll.setText(QCoreApplication.translate("LoginNew", u"\u5168\u90e8", None))
        self.proxyFilterProxy.setText(QCoreApplication.translate("LoginNew", u"ProxyIP", None))
        self.proxyFilterCf.setText(QCoreApplication.translate("LoginNew", u"\u4f18\u9009", None))
        self.proxyCutLabel.setText("")
        self.colNameLabel.setText(QCoreApplication.translate("LoginNew", u"\u8282\u70b9 / \u5730\u533a \u00b7 ISP", None))
        self.colSpeedLabel.setText(QCoreApplication.translate("LoginNew", u"\u5ef6\u8fdf / \u4e0b\u8f7d", None))
        ___qtablewidgetitem = self.tableWidget.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("LoginNew", u"\u8282\u70b9", None));
        self.label_15.setText(QCoreApplication.translate("LoginNew", u"API\u8d85\u65f6", None))
        self.apiTimeout.setItemText(0, QCoreApplication.translate("LoginNew", u"2", None))
        self.apiTimeout.setItemText(1, QCoreApplication.translate("LoginNew", u"5", None))
        self.apiTimeout.setItemText(2, QCoreApplication.translate("LoginNew", u"7", None))

        self.label_16.setText(QCoreApplication.translate("LoginNew", u"\u56fe\u7247\u8d85\u65f6", None))
        self.imgTimeout.setItemText(0, QCoreApplication.translate("LoginNew", u"2", None))
        self.imgTimeout.setItemText(1, QCoreApplication.translate("LoginNew", u"5", None))
        self.imgTimeout.setItemText(2, QCoreApplication.translate("LoginNew", u"7", None))
        self.imgTimeout.setItemText(3, QCoreApplication.translate("LoginNew", u"10", None))
        self.imgTimeout.setItemText(4, QCoreApplication.translate("LoginNew", u"15", None))

        self.label_17.setText(QCoreApplication.translate("LoginNew", u"DOH", None))
        self.dohTool.setText("")
        self.echBox.setText(QCoreApplication.translate("LoginNew", u"\u542f\u7528 ECH", None))
        self.http3Box.setText(QCoreApplication.translate("LoginNew", u"\u542f\u7528 HTTP3", None))
        self.label_26.setText(QCoreApplication.translate("LoginNew", u"\u83b7\u53d6\u5730\u533a", None))
        self.proxyIpLabel.setText("")
        self.label_22.setText(QCoreApplication.translate("LoginNew", u"\u81ea\u5b9a\u4e49 IP", None))
        self.label_25.setText(QCoreApplication.translate("LoginNew", u"*\u4f7f\u7528\u4ee3\u7406\u65f6IP\u5206\u6d41\u4e0d\u751f\u6548\uff0c\u63a8\u8350\u5f00\u542fECH\u529f\u80fd", None))
        self.proxyStatusLabel.setText("")
        self.proxyAdvButton.setText(QCoreApplication.translate("LoginNew", u"\u9ad8\u7ea7", None))
        self.testIpButton.setText(QCoreApplication.translate("LoginNew", u"\u6d4b\u8bd5 IP \u5206\u6d41", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_4), QCoreApplication.translate("LoginNew", u"\u5206\u6d41", None))
    # retranslateUi

