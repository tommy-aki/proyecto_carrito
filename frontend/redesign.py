import argparse
import logging
import sys
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLineEdit, QGraphicsOpacityEffect, QHeaderView, QMenu
from services.camera_service import CameraService
from services.cart_service import CartService
from services.rfid_service import RfidWorker, available_ports

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
STYLE = """
* { font-family:'Segoe UI'; } QMainWindow,QWidget { background:#F5F7FA; color:#111827; } QLabel { background:transparent; }
QLabel#title { font-size:30px; font-weight:700; } QLabel#overline { color:#6B7280; font-size:12px; font-weight:700; letter-spacing:1px; } QLabel#subtitle,QLabel#muted { color:#6B7280; font-size:14px; } QLabel#card_title { font-size:17px; font-weight:700; } QLabel#total { font-size:44px; font-weight:800; }
QFrame#card,QFrame#product,QFrame#summary { background:#FFF; border:1px solid #E5E7EB; border-radius:16px; } QFrame#summary { border:2px solid #D9EDE3; }
QPushButton { min-height:48px; padding:0 20px; border:0; border-radius:11px; background:#16A36A; color:#FFF; font-size:15px; font-weight:700; } QPushButton:hover { background:#128554; } QPushButton:pressed { background:#0D6D45; } QPushButton:disabled { background:#D1D5DB; color:#6B7280; } QPushButton#secondary { background:#FFF; border:1px solid #D1D5DB; color:#374151; } QPushButton#danger { background:#C94B4B; } QPushButton#nav { min-height:44px; padding-left:16px; text-align:left; border-radius:9px; background:transparent; color:#CBD5E1; font-size:14px; font-weight:600; } QPushButton#nav:hover,QPushButton#nav[selected="true"] { background:#243A32; color:#FFF; } QPushButton#sidebar_action { background:transparent; border:1px solid #64748B; color:#F8FAFC; }
QPushButton,QComboBox,QLineEdit,QListWidget,QTableWidget { qproperty-cursor: pointinghand; } QComboBox,QLineEdit { min-height:42px; border:1px solid #D1D5DB; border-radius:9px; padding:0 12px; background:#FFF; } QComboBox:focus,QLineEdit:focus { border:2px solid #7BC9A6; } QListWidget { border:0; background:transparent; outline:0; } QListWidget::item { min-height:52px; } QTableWidget { background:#FFF; border:1px solid #E5E7EB; border-radius:12px; gridline-color:#F3F4F6; } QTableWidget::item { padding:8px; } QHeaderView::section { background:#F9FAFB; border:0; padding:12px; color:#6B7280; font-weight:700; }
"""
def money(value): return f"L {float(value or 0):,.2f}"

class Toast(QFrame):
    def __init__(self, parent, title, message, error=False):
        super().__init__(parent); self.setObjectName("toast"); accent="#C94B4B" if error else "#16A36A"; self.setStyleSheet(f"QFrame#toast{{background:#FFF;border:1px solid #E5E7EB;border-left:5px solid {accent};border-radius:12px;}}")
        layout=QVBoxLayout(self); layout.setContentsMargins(16,12,22,12); layout.addWidget(QLabel(title,objectName="card_title")); body=QLabel(message,objectName="muted"); body.setWordWrap(True); layout.addWidget(body); effect=QGraphicsOpacityEffect(self); self.setGraphicsEffect(effect); effect.setOpacity(0); self.animation=QPropertyAnimation(effect,b"opacity",self); self.animation.setDuration(220); self.animation.setStartValue(0); self.animation.setEndValue(1); self.animation.start(); self.adjustSize(); QTimer.singleShot(2200,self.dismiss)
    def dismiss(self): self.animation.setDirection(QPropertyAnimation.Backward); self.animation.finished.connect(self.deleteLater); self.animation.start()

class MainWindow(QMainWindow):
    def __init__(self, demo=False):
        super().__init__(); self.demo=demo; self.service=CartService(); self.camera=CameraService(); self.worker=None; self.sale_id=None; self.pages={}; self.resize(1366,820); self.setMinimumSize(1040,680); self.setWindowTitle("SMARTCART"); self.setStyleSheet(STYLE); self.stack=QStackedWidget(); self.setCentralWidget(self.stack)
        self.home=self.make_home(); self.cart=self.make_cart(); self.checkout=self.make_checkout(); self.payment=self.make_payment(); self.result=self.make_result(); self.make_admin_shell(); self.service.start_session(); self.refresh_cart(); self.connect_serial(); self.set_click_cursors(); self.timer=QTimer(self); self.timer.timeout.connect(self.refresh_cart); self.timer.start(1500)
    def set_click_cursors(self):
        for button in self.findChildren(QPushButton): button.setCursor(QCursor(Qt.PointingHandCursor))
        for control_type in (QComboBox, QLineEdit):
            for control in self.findChildren(control_type): control.setCursor(QCursor(Qt.PointingHandCursor))
    def card(self,name="card"): frame=QFrame(); frame.setObjectName(name); return frame
    def add_page(self,key,page): self.pages[key]=page; self.stack.addWidget(page)
    def make_home(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(64,52,64,52); layout.setSpacing(18); layout.addWidget(QLabel("SMARTCART",objectName="title")); layout.addWidget(QLabel("Autonomous checkout, designed for effortless shopping.",objectName="subtitle")); layout.addSpacing(22); hero=self.card(); row=QHBoxLayout(hero); row.setContentsMargins(34,30,34,30); copy=QVBoxLayout(); copy.addWidget(QLabel("SELF-CHECKOUT PLATFORM",objectName="overline")); heading=QLabel("Compra más rápido.\nDisfruta el recorrido."); heading.setStyleSheet("font-size:34px;font-weight:800;"); copy.addWidget(heading); copy.addWidget(QLabel("RFID y visión preparados para una experiencia de retail sin fricción.",objectName="subtitle")); copy.addStretch(); row.addLayout(copy,3); status=QVBoxLayout(); self.home_status={}
        for name,value in (("RFID","ACTIVO"),("CÁMARA","SIN SEÑAL"),("SISTEMA","CONECTADO"),("ARDUINO","DESCONECTADO")):
            line=QHBoxLayout(); line.addWidget(QLabel("●")); line.addWidget(QLabel(name)); line.addStretch(); state=QLabel(value,objectName="muted"); line.addWidget(state); self.home_status[name]=state; status.addLayout(line)
        row.addLayout(status,2); layout.addWidget(hero); layout.addStretch(); actions=QHBoxLayout(); start=QPushButton("INICIAR COMPRA"); start.clicked.connect(lambda:self.navigate_to("cart")); actions.addWidget(start); admin=QPushButton("CENTRO DE CONTROL"); admin.setObjectName("secondary"); admin.clicked.connect(lambda:self.navigate_to("dashboard")); actions.addWidget(admin); actions.addStretch(); layout.addLayout(actions); self.demo_panel=self.card(); demo=QHBoxLayout(self.demo_panel); demo.addWidget(QLabel("MODO DEMO",objectName="overline"))
        for text,direction in (("RFID ENTRADA","ENTRADA"),("RFID SALIDA","SALIDA")):
            button=QPushButton(text); button.setObjectName("secondary"); button.clicked.connect(lambda _,d=direction:self.simulate_rfid(d)); demo.addWidget(button)
        unknown=QPushButton("UID DESCONOCIDO"); unknown.setObjectName("secondary"); unknown.clicked.connect(lambda:self.handle_rfid("ENTRADA","UNKNOWN99")); demo.addWidget(unknown); layout.addWidget(self.demo_panel); self.demo_panel.setVisible(self.demo); self.add_page("home",page); return page
    def make_cart(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(32,24,32,24); layout.setSpacing(16); header=QHBoxLayout(); identity=QVBoxLayout(); identity.setSpacing(4); identity.addWidget(QLabel("CARRITO C-01  ·  FÍSICO",objectName="overline")); identity.addWidget(QLabel("Tu compra",objectName="title")); self.cart_subtitle=QLabel(objectName="subtitle"); identity.addWidget(self.cart_subtitle); header.addLayout(identity); header.addStretch(); header.addWidget(QLabel("RFID  ●   CÁMARA  ●   SISTEMA  ●",objectName="muted")); home=QPushButton("INICIO"); home.setObjectName("secondary"); home.clicked.connect(lambda:self.navigate_to("home")); header.addWidget(home); layout.addLayout(header); content=QHBoxLayout(); content.setSpacing(20); left=QVBoxLayout(); left.setSpacing(10); left.addWidget(QLabel("PRODUCTOS DETECTADOS",objectName="overline")); self.empty_state=QLabel("◌\nTu carrito está vacío\nAcerca un producto al lector RFID para comenzar.",objectName="subtitle"); self.empty_state.setAlignment(Qt.AlignCenter); self.empty_state.setStyleSheet("padding:32px;font-size:16px;"); left.addWidget(self.empty_state); self.items=QListWidget(); left.addWidget(self.items); content.addLayout(left,7); self.summary=self.card("summary"); side=QVBoxLayout(self.summary); side.setContentsMargins(24,24,24,24); side.addWidget(QLabel("RESUMEN DE COMPRA",objectName="overline")); side.addWidget(QLabel("TOTAL",objectName="muted")); self.total=QLabel("L 0.00",objectName="total"); side.addWidget(self.total); self.count=QLabel(objectName="muted"); side.addWidget(self.count); side.addStretch(); checkout=QPushButton("FINALIZAR COMPRA  →"); checkout.clicked.connect(lambda:self.navigate_to("checkout")); side.addWidget(checkout); content.addWidget(self.summary,3); layout.addLayout(content,5); activity=self.card(); activity_layout=QVBoxLayout(activity); activity_layout.setContentsMargins(20,12,20,12); activity_layout.addWidget(QLabel("ACTIVIDAD RECIENTE",objectName="overline")); self.events=QListWidget(); activity_layout.addWidget(self.events); layout.addWidget(activity,2); self.add_page("cart",page); return page
    def stepper(self,active):
        row=QHBoxLayout()
        for index,name in enumerate(("COMPRA","REVISIÓN","PAGO","SALIDA"),1): label=QLabel(f"{'✓' if index<active else index}  {name}"); label.setStyleSheet(f"color:{'#16A36A' if index<=active else '#9CA3AF'};font-size:13px;font-weight:800;padding:10px 18px;"); row.addWidget(label); row.addStretch()
        return row
    def make_checkout(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(80,38,80,38); layout.addLayout(self.stepper(2)); layout.addWidget(QLabel("REVISIÓN",objectName="overline")); layout.addWidget(QLabel("Revisa tu compra",objectName="title")); self.checkout_list=QListWidget(); layout.addWidget(self.checkout_list); self.checkout_total=QLabel(objectName="total"); layout.addWidget(self.checkout_total); row=QHBoxLayout(); back=QPushButton("← SEGUIR COMPRANDO"); back.setObjectName("secondary"); back.clicked.connect(lambda:self.navigate_to("cart")); row.addWidget(back); row.addStretch(); proceed=QPushButton("CONTINUAR AL PAGO →"); proceed.clicked.connect(self.begin_checkout); row.addWidget(proceed); layout.addLayout(row); self.add_page("checkout",page); return page
    def make_payment(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(80,38,80,38); layout.addLayout(self.stepper(3)); layout.addWidget(QLabel("PAGO",objectName="overline")); layout.addWidget(QLabel("Elige cómo pagar",objectName="title")); self.payment_total=QLabel(objectName="total"); layout.addWidget(self.payment_total); self.method=QComboBox(); self.method.addItem("▣  TARJETA · Inserta o acerca tu tarjeta","TARJETA_SIMULADA"); self.method.addItem("▦  QR · Escanea desde tu móvil","QR_SIMULADO"); self.method.addItem("▤  EFECTIVO · Confirma el pago recibido","EFECTIVO_SIMULADO"); self.method.setMinimumHeight(64); layout.addWidget(self.method); layout.addStretch(); layout.addWidget(QLabel("MODO DEMOSTRACIÓN",objectName="overline")); row=QHBoxLayout(); approve=QPushButton("SIMULAR APROBACIÓN"); approve.clicked.connect(lambda:self.process_payment(True)); row.addWidget(approve); reject=QPushButton("SIMULAR RECHAZO"); reject.setObjectName("danger"); reject.clicked.connect(lambda:self.process_payment(False)); row.addWidget(reject); layout.addLayout(row); self.add_page("payment",page); return page
    def make_result(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(24,24,24,24); layout.setAlignment(Qt.AlignCenter); self.result_icon=QLabel("✓"); self.result_icon.setAlignment(Qt.AlignCenter); self.result_icon.setFixedSize(84,84); layout.addWidget(self.result_icon,alignment=Qt.AlignCenter); self.result_title=QLabel("Pago aprobado",objectName="title"); layout.addWidget(self.result_title,alignment=Qt.AlignCenter); self.result_text=QLabel(objectName="subtitle"); self.result_text.setAlignment(Qt.AlignCenter); layout.addWidget(self.result_text); self.result_action=QPushButton("FINALIZAR Y SALIR"); self.result_action.clicked.connect(self.finish_result); layout.addWidget(self.result_action,alignment=Qt.AlignCenter); self.result_retry=QPushButton("INTENTAR NUEVAMENTE"); self.result_retry.setObjectName("secondary"); self.result_retry.clicked.connect(lambda:self.navigate_to("payment")); self.result_retry.hide(); layout.addWidget(self.result_retry,alignment=Qt.AlignCenter); self.result_cancel=QPushButton("CANCELAR VENTA"); self.result_cancel.setObjectName("danger"); self.result_cancel.clicked.connect(self.cancel_sale); self.result_cancel.hide(); layout.addWidget(self.result_cancel,alignment=Qt.AlignCenter); receipt=QPushButton("VER RECIBO"); receipt.setObjectName("secondary"); receipt.clicked.connect(self.show_receipt); layout.addWidget(receipt,alignment=Qt.AlignCenter); self.add_page("result",page); return page
    def make_admin_shell(self):
        page=QWidget(); root=QHBoxLayout(page); root.setContentsMargins(0,0,0,0); root.setSpacing(0); sidebar=QWidget(); sidebar.setFixedWidth(236); sidebar.setStyleSheet("background:#111827;"); nav=QVBoxLayout(sidebar); nav.setContentsMargins(18,28,18,22); nav.addWidget(QLabel("SMARTCART",objectName="brand")); nav.addWidget(QLabel("CONTROL CENTER",objectName="overline")); nav.addSpacing(22); self.nav_buttons={}
        entries=(('dashboard','⌂   Dashboard'),('carts','▣   Carritos'),('products','□   Productos'),('rfid','⌁   RFID'),('inventory','▤   Inventario'),('sales','▥   Ventas'),('events','≡   Eventos'),('devices','◉   Dispositivos'),('camera','▧   Cámara'))
        for key,text in entries:
            button=QPushButton(text); button.setObjectName("nav"); button.clicked.connect(lambda _,k=key:self.navigate_to(k)); nav.addWidget(button); self.nav_buttons[key]=button
        nav.addStretch(); client=QPushButton("MODO CLIENTE"); client.setObjectName("sidebar_action"); client.clicked.connect(lambda:self.navigate_to("home")); nav.addWidget(client); root.addWidget(sidebar)
        self.admin_content=QStackedWidget(); root.addWidget(self.admin_content,1); self.admin_shell=page; self.add_page("admin",page)
        for key in ('dashboard','carts','products','rfid','inventory','sales','events','devices','camera'): self.make_admin_page(key)
        self.navigate_to("dashboard")
    def make_admin_page(self,key):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(34,24,34,24); titles={'dashboard':'DASHBOARD','carts':'CARRITOS','products':'PRODUCTOS','rfid':'RFID','inventory':'INVENTARIO','sales':'VENTAS','events':'EVENTOS','devices':'DISPOSITIVOS','camera':'CÁMARA'}; layout.addWidget(QLabel(titles[key],objectName="title")); subtitle='C-01 · FÍSICO · Cámara principal' if key=='camera' else 'C-01 · FÍSICO' if key in ('rfid','devices') else '';
        if subtitle: layout.addWidget(QLabel(subtitle,objectName="subtitle"))
        if key=='dashboard': self.dashboard_body(layout)
        elif key=='carts': self.carts_body(layout)
        elif key=='products': self.products_body(layout)
        elif key=='rfid': self.rfid_body(layout)
        elif key=='inventory': self.inventory_body(layout)
        elif key=='sales': self.sales_body(layout)
        elif key=='events': self.events_body(layout)
        elif key=='devices': self.devices_body(layout)
        else: self.camera_body(layout)
        self.admin_content.addWidget(page); self.admin_pages=getattr(self,'admin_pages',{}); self.admin_pages[key]=page
    def dashboard_body(self,layout):
        self.admin_cards=QGridLayout(); layout.addLayout(self.admin_cards); self.admin_values={}; self.dashboard_carts=QHBoxLayout(); layout.addWidget(QLabel("CARRITOS",objectName="card_title")); layout.addLayout(self.dashboard_carts); layout.addWidget(QLabel("ÚLTIMAS VENTAS",objectName="card_title")); self.sales_table=QTableWidget(0,4); self.sales_table.setHorizontalHeaderLabels(("VENTA","TOTAL","ESTADO","FECHA")); layout.addWidget(self.sales_table)
    def carts_body(self,layout):
        self.carts_list=QListWidget(); layout.addWidget(self.carts_list); self.populate_carts()
    def products_body(self,layout):
        row=QHBoxLayout(); self.product_search=QLineEdit(); self.product_search.setPlaceholderText("Buscar por nombre o código..."); self.product_search.textChanged.connect(self.refresh_products); row.addWidget(self.product_search,1); add=QPushButton("+ NUEVO PRODUCTO"); add.setMinimumWidth(240); add.clicked.connect(self.create_product); row.addWidget(add); layout.addLayout(row); self.products_table=QTableWidget(0,8); self.products_table.setHorizontalHeaderLabels(("PRODUCTO","CÓDIGO","PRECIO","STOCK","MÍNIMO","MÉTODO","ESTADO","ACCIONES")); header=self.products_table.horizontalHeader(); header.setSectionResizeMode(0,QHeaderView.Stretch); header.setSectionResizeMode(1,QHeaderView.ResizeToContents); header.setSectionResizeMode(2,QHeaderView.ResizeToContents); header.setSectionResizeMode(3,QHeaderView.ResizeToContents); header.setSectionResizeMode(4,QHeaderView.ResizeToContents); header.setSectionResizeMode(5,QHeaderView.ResizeToContents); header.setSectionResizeMode(6,QHeaderView.ResizeToContents); header.setSectionResizeMode(7,QHeaderView.Fixed); self.products_table.setColumnWidth(7,130); layout.addWidget(self.products_table)
    def rfid_body(self,layout):
        reader=self.card(); reader_layout=QHBoxLayout(reader); reader_layout.setContentsMargins(20,16,20,16); reader_text=QVBoxLayout(); reader_text.addWidget(QLabel("LECTOR RFID",objectName="card_title")); self.rfid_uid=QLabel("●  ESPERANDO ETIQUETA",objectName="subtitle"); reader_text.addWidget(self.rfid_uid); reader_text.addWidget(QLabel("Acerca una etiqueta al lector para detectarla.",objectName="muted")); reader_layout.addLayout(reader_text); reader_layout.addStretch(); demo=QVBoxLayout(); demo.addWidget(QLabel("MODO DEMO",objectName="overline")); simulate=QPushButton("SIMULAR UID"); simulate.setObjectName("secondary"); simulate.setMinimumWidth(180); simulate.clicked.connect(lambda:self.open_association("SIM-DEMO-01")); demo.addWidget(simulate); reader_layout.addLayout(demo); layout.addWidget(reader); self.tags_table=QTableWidget(0,5); self.tags_table.setHorizontalHeaderLabels(("UID","PRODUCTO","ESTADO","FECHA","ACCIÓN")); header=self.tags_table.horizontalHeader(); header.setSectionResizeMode(0,QHeaderView.ResizeToContents); header.setSectionResizeMode(1,QHeaderView.Stretch); header.setSectionResizeMode(2,QHeaderView.ResizeToContents); header.setSectionResizeMode(3,QHeaderView.ResizeToContents); header.setSectionResizeMode(4,QHeaderView.Fixed); self.tags_table.setColumnWidth(4,150); layout.addWidget(self.tags_table)
    def inventory_body(self,layout):
        row=QHBoxLayout(); self.inventory_search=QLineEdit(); self.inventory_search.setPlaceholderText("Buscar inventario..."); self.inventory_search.textChanged.connect(self.refresh_inventory); row.addWidget(self.inventory_search); add=QPushButton("+ AJUSTE"); add.clicked.connect(self.adjust_stock); row.addWidget(add); layout.addLayout(row); self.inventory_table=QTableWidget(0,4); self.inventory_table.setHorizontalHeaderLabels(("PRODUCTO","STOCK","MÍNIMO","ESTADO")); layout.addWidget(self.inventory_table)
    def sales_body(self,layout):
        self.admin_sales=QTableWidget(0,5); self.admin_sales.setHorizontalHeaderLabels(("NÚMERO","FECHA","TOTAL","ESTADO","MÉTODO")); self.admin_sales.itemSelectionChanged.connect(self.show_sale_detail); layout.addWidget(self.admin_sales); self.sale_detail=QLabel("Selecciona una venta para ver su detalle.",objectName="subtitle"); layout.addWidget(self.sale_detail)
    def events_body(self,layout):
        self.event_filter=QComboBox(); self.event_filter.addItem("TODOS",None); self.event_filter.addItem("RFID","RFID"); self.event_filter.addItem("VISIÓN","VISION"); self.event_filter.addItem("IGNORADOS","IGNORADA"); self.event_filter.currentIndexChanged.connect(self.refresh_events); layout.addWidget(self.event_filter); self.events_table=QTableWidget(0,6); self.events_table.setHorizontalHeaderLabels(("HORA","ORIGEN","DIRECCIÓN","PRODUCTO","UID","ESTADO")); layout.addWidget(self.events_table)
    def devices_body(self,layout): self.devices_list=QListWidget(); layout.addWidget(self.devices_list); self.refresh_devices()
    def camera_body(self,layout):
        card=self.card(); card.setMaximumWidth(860); body=QVBoxLayout(card); body.setContentsMargins(32,28,32,28); body.setAlignment(Qt.AlignCenter); body.addWidget(QLabel("CÁMARA SIN SEÑAL",objectName="title"),alignment=Qt.AlignCenter); body.addWidget(QLabel("No encontramos una cámara conectada.",objectName="subtitle"),alignment=Qt.AlignCenter); retry=QPushButton("REINTENTAR"); retry.setMinimumWidth(180); retry.clicked.connect(self.retry_camera); body.addWidget(retry,alignment=Qt.AlignCenter); body.addWidget(QLabel("MODO DEMOSTRACIÓN",objectName="overline"),alignment=Qt.AlignCenter); if_demo=QPushButton("SIMULAR DETECCIÓN"); if_demo.setObjectName("secondary"); if_demo.setMinimumWidth(210); if_demo.clicked.connect(lambda:self.notify("Visión simulada","Producto reconocido · Confianza 94.7 %")); body.addWidget(if_demo,alignment=Qt.AlignCenter); layout.addWidget(card,alignment=Qt.AlignTop|Qt.AlignHCenter); layout.addStretch()
    def navigate_to(self,key):
        if key in self.admin_pages:
            self.admin_content.setCurrentWidget(self.admin_pages[key]); self.stack.setCurrentWidget(self.admin_shell); self.refresh_admin_page(key)
        elif key in self.pages: self.stack.setCurrentWidget(self.pages[key])
        if key in self.nav_buttons:
            for name,button in self.nav_buttons.items(): button.setProperty("selected",name==key); button.style().unpolish(button); button.style().polish(button)
    def refresh_admin_page(self,key):
        if key=='dashboard': self.refresh_admin()
        elif key=='products': self.refresh_products()
        elif key=='rfid': self.refresh_tags()
        elif key=='inventory': self.refresh_inventory()
        elif key=='sales': self.refresh_sales()
        elif key=='events': self.refresh_events()
        elif key=='devices': self.refresh_devices()
    def refresh_cart(self):
        try:
            session,products,events=self.service.snapshot(); self.items.clear(); count=0
            for product in products:
                item=QListWidgetItem(); widget=self.card("product"); row=QHBoxLayout(widget); row.setContentsMargins(18,14,18,14); detail=QVBoxLayout(); detail.addWidget(QLabel(product[1],objectName="card_title")); detail.addWidget(QLabel(f"{product[2]} × {money(product[3])} · RFID",objectName="muted")); row.addLayout(detail); row.addStretch(); row.addWidget(QLabel(money(product[4]),objectName="card_title")); self.items.addItem(item); self.items.setItemWidget(item,widget); count+=product[2]
            self.total.setText(money(session[4])); self.count.setText(f"{count} artículos"); self.cart_subtitle.setText(f"{count} artículos en el carrito"); self.empty_state.setVisible(not products); self.items.setVisible(bool(products)); self.events.clear(); [self.events.addItem(f"{event[0]}  {event[2]} · {event[4] or event[3] or ''}") for event in events[:4]]
        except Exception as error: logging.exception("No se pudo actualizar el carrito: %s",error)
    def refresh_checkout(self):
        session,products,_=self.service.snapshot(); self.checkout_list.clear(); [self.checkout_list.addItem(f"{p[1]}  ·  {p[2]} unidad(es)  ·  {money(p[4])}") for p in products]; self.checkout_total.setText(f"TOTAL  {money(session[4])}"); self.payment_total.setText(f"TOTAL A PAGAR  {money(session[4])}")
    def begin_checkout(self):
        try:self.sale_id=self.service.begin_checkout(); self.notify("Compra bloqueada para pago","La sesión está PAGANDO."); self.navigate_to("payment")
        except Exception as error:self.notify("No se puede continuar",str(error),True)
    def process_payment(self,approved):
        try:self.service.pay(self.sale_id,self.method.currentData(),approved); self.result_title.setText("Pago aprobado" if approved else "Pago rechazado"); self.result_icon.setText("✓" if approved else "!"); self.result_icon.setStyleSheet(f"color:#FFF;background:{'#16A36A' if approved else '#C94B4B'};border-radius:42px;font-size:42px;font-weight:800;"); self.result_text.setText(f"{money(self.service.snapshot()[0][4])}\n{'SALIDA AUTORIZADA' if approved else 'No fue posible completar la operación.'}\nVenta #{self.sale_id}"); self.result_action.setVisible(approved); self.result_retry.setVisible(not approved); self.result_cancel.setVisible(not approved); self.navigate_to("result"); self.notify("Pago aprobado" if approved else "Pago rechazado",money(self.service.snapshot()[0][4]),not approved)
        except Exception as error:self.notify("Pago",str(error),True)
    def show_receipt(self): QMessageBox.information(self,"Recibo",f"SMARTCART\nVenta #{self.sale_id}\n{self.result_text.text()}")
    def finish_result(self): self.service.new_session(); self.refresh_cart(); self.navigate_to("home")
    def cancel_sale(self):
        try:self.service.cancel(self.sale_id); self.service.new_session(); self.notify("Venta cancelada","La sesi�n qued� liberada."); self.navigate_to("home")
        except Exception as error:self.notify("No se pudo cancelar",str(error),True)
    def handle_rfid(self,direction,uid):
        try: message=self.service.rfid(direction,uid); self.refresh_cart(); self.notify("Producto agregado" if direction=="ENTRADA" else "Producto retirado",message,"no registrado" in message.lower())
        except Exception as error:self.notify("RFID",str(error),True)
    def simulate_rfid(self,direction): self.handle_rfid(direction,"4A3B2C1D")
    def notify(self,title,message,error=False): toast=Toast(self,title,message,error); toast.move(self.width()-toast.width()-28,24); toast.show(); toast.raise_()
    def refresh_ports(self): self.port_combo.clear(); self.port_combo.addItems(available_ports())
    def connect_selected(self):
        if self.demo:self.notify("Modo demo","El hardware está desactivado."); return
        if self.worker:self.worker.stop()
        if not self.port_combo.currentText():self.notify("Arduino desconectado","No hay puertos COM disponibles.",True); return
        self.worker=RfidWorker(self.port_combo.currentText()); self.worker.reading.connect(self.handle_rfid); self.worker.connection.connect(lambda ok,text:self.home_status["ARDUINO"].setText("CONECTADO" if ok else "DESCONECTADO")); self.worker.start()
    def connect_serial(self):
        if self.demo:self.home_status["ARDUINO"].setText("MODO DEMO"); return
        self.refresh_ports(); self.connect_selected()
    def refresh_admin(self):
        summary=self.service.admin_summary()
        for index,(label,key,detail) in enumerate((("VENTAS HOY","ventas_hoy","operaciones"),("COMPRAS","productos","productos activos"),("SESIONES ACTIVAS","sesiones_activas","en tiempo real"),("STOCK BAJO","stock_bajo","requieren atención"))):
            if key not in self.admin_values:
                box=self.card(); box_layout=QVBoxLayout(box); box_layout.addWidget(QLabel(label,objectName="overline")); value=QLabel("0",objectName="total"); box_layout.addWidget(value); box_layout.addWidget(QLabel(detail,objectName="muted")); self.admin_values[key]=value; self.admin_cards.addWidget(box,0,index)
            self.admin_values[key].setText(str(summary[key]))
        while self.dashboard_carts.count():
            item=self.dashboard_carts.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        session, products, _ = self.service.snapshot(); total=session[4] if session else 0; count=sum(product[2] for product in products)
        for cart_id, label, state, detail in (("C-01", "FÍSICO", session[2] if session else "DISPONIBLE", f"{count} artículos  ·  {money(total)}"), ("C-02", "DEMO", "DISPONIBLE", "Datos de demostración"), ("C-03", "DEMO", "DISPONIBLE", "Datos de demostración"), ("C-04", "DEMO", "DISPONIBLE", "Datos de demostración")):
            card=self.card(); card_layout=QVBoxLayout(card); header=QHBoxLayout(); header.addWidget(QLabel(cart_id,objectName="card_title")); header.addStretch(); header.addWidget(QLabel(label,objectName="overline")); card_layout.addLayout(header); card_layout.addWidget(QLabel(state,objectName="success")); card_layout.addWidget(QLabel(detail,objectName="muted")); self.dashboard_carts.addWidget(card)
        self.sales_table.setRowCount(0); [self._table_row(self.sales_table,sale) for sale in summary["ventas"]]
    def _table_row(self,table,values): row=table.rowCount(); table.insertRow(row); table.setRowHeight(row,56); [table.setItem(row,col,QTableWidgetItem(str(value))) for col,value in enumerate(values)]
    def populate_carts(self):
        self.carts_list.clear(); session,products,_=self.service.snapshot(); total=session[4] if session else 0; count=sum(p[2] for p in products); self.carts_list.itemClicked.connect(lambda item:self.notify("Carrito C-01" if item.text().startswith("C-01") else "Datos de demostraci�n",item.text())); self.carts_list.addItem(f"C-01  ·  FÍSICO  ·  COMPRANDO  ·  {count} productos  ·  {money(total)}"); [self.carts_list.addItem(f"{key}  ·  DEMO  ·  DISPONIBLE  ·  DATOS DE DEMOSTRACIÓN") for key in ("C-02","C-03","C-04")]
    def refresh_products(self):
        if not hasattr(self,'products_table'): return
        text=self.product_search.text().lower(); self.products_table.setRowCount(0)
        for p in self.service.products():
            if text and text not in p[2].lower() and text not in p[1].lower(): continue
            row=self.products_table.rowCount(); self.products_table.insertRow(row); values=(p[2],p[1],money(p[3]),p[4],p[5],p[6],"ACTIVO" if p[7] else "INACTIVO"); [self.products_table.setItem(row,col,QTableWidgetItem(str(value))) for col,value in enumerate(values)]; edit=QPushButton("EDITAR"); edit.setObjectName("secondary"); edit.setMinimumWidth(76); edit.clicked.connect(lambda _,product=p:self.edit_product(product)); actions=QWidget(); action_layout=QHBoxLayout(actions); action_layout.setContentsMargins(4,0,4,0); action_layout.addWidget(edit); menu_button=QPushButton("..."); menu_button.setObjectName("secondary"); menu_button.setFixedSize(36,36); menu=QMenu(menu_button); detail=menu.addAction("Ver detalles"); detail.triggered.connect(lambda _,product=p:self.notify("Detalle de producto",f"{product[2]} · {money(product[3])}")); toggle=menu.addAction("Desactivar" if p[7] else "Activar"); toggle.triggered.connect(lambda _,pid=p[0]:self.deactivate_product(pid) if p[7] else self.notify("Producto inactivo","Activa el producto desde operaciones administrativas.")); menu_button.clicked.connect(lambda:menu.exec(menu_button.mapToGlobal(menu_button.rect().bottomLeft()))); action_layout.addWidget(menu_button); self.products_table.setCellWidget(row,7,actions)
    def create_product(self):
        code,ok=QInputDialog.getText(self,"Nuevo producto","Código:"); name,ok2=QInputDialog.getText(self,"Nuevo producto","Nombre:")
        if ok and ok2:
            try:self.service.create_product(code,name,0,0,0); self.refresh_products(); self.notify("Guardado correctamente","Producto creado.")
            except Exception as error:self.notify("No se pudo crear",str(error),True)
    def edit_product(self, product):
        name, ok = QInputDialog.getText(self, "Editar producto", "Nombre:", text=product[2])
        if ok:
            try:
                price, ok_price = QInputDialog.getDouble(self, "Editar producto", "Precio:", float(product[3]), 0, 100000, 2)
                minimum, ok_minimum = QInputDialog.getInt(self, "Editar producto", "Stock mínimo:", product[5], 0)
                if ok_price and ok_minimum:
                    self.service.update_product(product[0], name, price, minimum); self.refresh_products(); self.notify("Guardado correctamente", "Producto actualizado.")
            except Exception as error: self.notify("No se pudo editar", str(error), True)
    def deactivate_product(self,pid):
        try:self.service.deactivate_product(pid); self.refresh_products(); self.notify("Producto actualizado","Producto desactivado.")
        except Exception as error:self.notify("Error",str(error),True)
    def refresh_tags(self):
        self.tags_table.setRowCount(0)
        for tag in self.service.admin_data("etiquetas"):
            row=self.tags_table.rowCount(); self.tags_table.insertRow(row); self.tags_table.setRowHeight(row,52); [self.tags_table.setItem(row,col,QTableWidgetItem(str(value))) for col,value in enumerate(tag[:4])]; button=QPushButton("DESACTIVAR" if tag[2]=="ACTIVA" else "ACTIVAR"); button.setObjectName("secondary"); button.setMinimumWidth(110); button.clicked.connect(lambda _,tid=tag[4],state=tag[2]:self.toggle_tag(tid,state)); self.tags_table.setCellWidget(row,4,button)
    def open_association(self,uid):
        products=self.service.products(); names=[p[2] for p in products]; name,ok=QInputDialog.getItem(self,"Asociar etiqueta RFID","Producto:",names,0,False)
        if ok:
            try:self.service.associate(uid,next(p[0] for p in products if p[2]==name)); self.refresh_tags(); self.notify("Guardado correctamente",f"Etiqueta {uid} asociada.")
            except Exception as error:self.notify("RFID",str(error),True)
    def toggle_tag(self,tid,state): self.service.set_tag_state(tid,"INACTIVA" if state=="ACTIVA" else "ACTIVA"); self.refresh_tags(); self.notify("RFID actualizado","Estado modificado.")
    def refresh_inventory(self):
        text=self.inventory_search.text().lower(); self.inventory_table.setRowCount(0)
        for p in self.service.products():
            if text and text not in p[2].lower():continue
            state="AGOTADO" if p[4]==0 else "STOCK BAJO" if p[4]<=p[5] else "DISPONIBLE"; self._table_row(self.inventory_table,(p[2],p[4],p[5],state))
    def adjust_stock(self):
        products=self.service.products(); name,ok=QInputDialog.getItem(self,"Ajuste de inventario","Producto:",[p[2] for p in products],0,False); qty,ok2=QInputDialog.getInt(self,"Ajuste de inventario","Cantidad:",1,1)
        if ok and ok2:
            adjustment,accepted=QInputDialog.getItem(self,"Ajuste de inventario","Tipo:",["AJUSTE_ENTRADA","AJUSTE_SALIDA"],0,False)
            if accepted:
                try:self.service.adjust_stock(next(p[0] for p in products if p[2]==name),qty,adjustment); self.refresh_inventory(); self.notify("Guardado correctamente","Movimiento registrado.")
                except Exception as error:self.notify("Inventario",str(error),True)
    def refresh_sales(self):
        self.admin_sales.setRowCount(0); [self._table_row(self.admin_sales,(v[1],v[2],money(v[3]),v[4],v[5])) for v in self.service.admin_data("ventas")]
    def show_sale_detail(self):
        row=self.admin_sales.currentRow()
        if row>=0:
            number=self.admin_sales.item(row,0).text(); sale=next((v for v in self.service.admin_data("ventas") if v[1]==number),None); self.sale_detail.setText("\n".join(f"{d[0]} · {d[1]} · {money(d[3])}" for d in self.service.admin_data("detalle_venta",sale[0])) if sale else "Sin detalle")
    def refresh_events(self):
        self.events_table.setRowCount(0); [self._table_row(self.events_table,e) for e in self.service.admin_data("eventos",self.event_filter.currentData())]
    def refresh_devices(self): self.devices_list.clear(); [self.devices_list.addItem(f"{d[1]}  ·  {d[3]}  ·  {d[0]}") for d in self.service.admin_data("dispositivos")]
    def retry_camera(self): self.notify("Cámara","No se encontró una cámara disponible." if not self.camera.start() else "Cámara conectada.",not bool(self.camera.capture))
    def show_receipt(self): QMessageBox.information(self,"Recibo",f"SMARTCART\nVenta #{self.sale_id}\n{self.result_text.text()}")
    def keyPressEvent(self,event):
        if event.key()==Qt.Key_F11:self.showNormal() if self.isFullScreen() else self.showFullScreen()
        elif event.key()==Qt.Key_Escape and self.isFullScreen():self.showNormal()
        else:super().keyPressEvent(event)
    def closeEvent(self,event):
        if self.worker:self.worker.stop()
        self.camera.stop(); event.accept()

def main():
    parser=argparse.ArgumentParser(description="SmartCart PySide6"); parser.add_argument("--demo",action="store_true"); args=parser.parse_args(); app=QApplication(sys.argv); window=MainWindow(args.demo); window.show(); sys.exit(app.exec())
if __name__=="__main__":main()

