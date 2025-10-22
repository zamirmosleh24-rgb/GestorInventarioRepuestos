import os
import json
import requests
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

# -------------------------
# Configuración
# -------------------------
SERVER_URL = "http://localhost:5000"  # Cambia a la IP del servidor si no está en localhost
API_KEY = "tu_clave_api_aqui"  # Ingresar la clave API al iniciar

# -------------------------
# Funciones de sincronización
# -------------------------
def sync_inventory():
    try:
        response = requests.get(f"{SERVER_URL}/items", headers={"X-API-KEY": API_KEY})
        if response.status_code == 200:
            inventory = response.json()["items"]
            return inventory
        else:
            messagebox.showerror("Error", "No se pudo sincronizar el inventario.")
            return []
    except requests.exceptions.RequestException as e:
        messagebox.showerror("Error", f"No se pudo conectar al servidor: {e}")
        return []

def update_inventory_display():
    inventory = sync_inventory()
    for row in treeview.get_children():
        treeview.delete(row)
    for item in inventory:
        treeview.insert("", "end", values=(item["id"], item["nombre"], item["descripcion"], item["cantidad"], item["precio_usd"], item["precio_bs"]))

def refresh_inventory():
    inventory = sync_inventory()
    for row in treeview.get_children():
        treeview.delete(row)
    for item in inventory:
        treeview.insert("", "end", values=(item["id"], item["nombre"], item["descripcion"], item["cantidad"], item["precio_usd"], item["precio_bs"]))
    window.after(10000, refresh_inventory)  # Refrescar cada 10 segundos

# -------------------------
# Funciones CRUD
# -------------------------
def add_item():
    item_id = simpledialog.askstring("Agregar artículo", "ID del artículo:")
    if not item_id:
        return
    nombre = simpledialog.askstring("Agregar artículo", "Nombre del artículo:")
    if not nombre:
        return
    descripcion = simpledialog.askstring("Agregar artículo", "Descripción del artículo:")
    cantidad = simpledialog.askinteger("Agregar artículo", "Cantidad disponible:")
    precio_usd = simpledialog.askfloat("Agregar artículo", "Precio en USD:")
    precio_bs = simpledialog.askfloat("Agregar artículo", "Precio en Bs:")
    
    item_data = {
        "id": item_id,
        "nombre": nombre,
        "descripcion": descripcion,
        "cantidad": cantidad,
        "precio_usd": precio_usd,
        "precio_bs": precio_bs
    }

    response = requests.post(f"{SERVER_URL}/items", json=item_data, headers={"X-API-KEY": API_KEY})
    if response.status_code == 200:
        messagebox.showinfo("Éxito", "Artículo agregado correctamente.")
        update_inventory_display()
    else:
        messagebox.showerror("Error", "No se pudo agregar el artículo.")

def edit_item():
    selected_item = treeview.selection()
    if not selected_item:
        messagebox.showwarning("Advertencia", "Selecciona un artículo para editar.")
        return

    item_id = treeview.item(selected_item, "values")[0]
    item = get_item_by_id(item_id)

    new_name = simpledialog.askstring("Editar artículo", f"Nuevo nombre ({item['nombre']}):", initialvalue=item['nombre'])
    new_desc = simpledialog.askstring("Editar artículo", f"Nuevo descripción ({item['descripcion']}):", initialvalue=item['descripcion'])
    new_qty = simpledialog.askinteger("Editar artículo", f"Nueva cantidad ({item['cantidad']}):", initialvalue=item['cantidad'])
    new_price_usd = simpledialog.askfloat("Editar artículo", f"Nuevo precio USD ({item['precio_usd']}):", initialvalue=item['precio_usd'])
    new_price_bs = simpledialog.askfloat("Editar artículo", f"Nuevo precio Bs ({item['precio_bs']}):", initialvalue=item['precio_bs'])

    updated_item = {
        "id": item_id,
        "nombre": new_name,
        "descripcion": new_desc,
        "cantidad": new_qty,
        "precio_usd": new_price_usd,
        "precio_bs": new_price_bs
    }

    response = requests.put(f"{SERVER_URL}/items/{item_id}", json=updated_item, headers={"X-API-KEY": API_KEY})
    if response.status_code == 200:
        messagebox.showinfo("Éxito", "Artículo editado correctamente.")
        update_inventory_display()
    else:
        messagebox.showerror("Error", "No se pudo editar el artículo.")

def delete_item():
    selected_item = treeview.selection()
    if not selected_item:
        messagebox.showwarning("Advertencia", "Selecciona un artículo para eliminar.")
        return

    item_id = treeview.item(selected_item, "values")[0]
    confirm = messagebox.askyesno("Eliminar artículo", f"¿Estás seguro de eliminar el artículo con ID {item_id}?")
    
    if confirm:
        response = requests.delete(f"{SERVER_URL}/items/{item_id}", headers={"X-API-KEY": API_KEY})
        if response.status_code == 200:
            messagebox.showinfo("Éxito", "Artículo eliminado correctamente.")
            update_inventory_display()
        else:
            messagebox.showerror("Error", "No se pudo eliminar el artículo.")

def sell_item():
    selected_item = treeview.selection()
    if not selected_item:
        messagebox.showwarning("Advertencia", "Selecciona un artículo para vender.")
        return

    item_id = treeview.item(selected_item, "values")[0]
    qty = simpledialog.askinteger("Vender artículo", "Cantidad a vender:")
    
    if qty is None or qty <= 0:
        messagebox.showwarning("Advertencia", "La cantidad debe ser un número positivo.")
        return

    response = requests.post(f"{SERVER_URL}/sell", json={"id": item_id, "quantity": qty}, headers={"X-API-KEY": API_KEY})
    if response.status_code == 200:
        messagebox.showinfo("Éxito", "Venta registrada correctamente.")
        update_inventory_display()
    else:
        messagebox.showerror("Error", "No se pudo realizar la venta.")

def return_item():
    selected_item = treeview.selection()
    if not selected_item:
        messagebox.showwarning("Advertencia", "Selecciona un artículo para devolver.")
        return

    item_id = treeview.item(selected_item, "values")[0]
    qty = simpledialog.askinteger("Devolver artículo", "Cantidad a devolver:")
    
    if qty is None or qty <= 0:
        messagebox.showwarning("Advertencia", "La cantidad debe ser un número positivo.")
        return

    response = requests.post(f"{SERVER_URL}/return", json={"id": item_id, "quantity": qty}, headers={"X-API-KEY": API_KEY})
    if response.status_code == 200:
        messagebox.showinfo("Éxito", "Devolución registrada correctamente.")
        update_inventory_display()
    else:
        messagebox.showerror("Error", "No se pudo realizar la devolución.")

# -------------------------
# UI Principal (Tkinter)
# -------------------------
window = tk.Tk()
window.title("Gestor de Inventario de Repuestos")
window.geometry("800x600")

frame = tk.Frame(window)
frame.pack(padx=20, pady=20)

columns = ("ID", "Nombre", "Descripción", "Cantidad", "Precio USD", "Precio Bs")
treeview = ttk.Treeview(frame, columns=columns, show="headings", height=10)

for col in columns:
    treeview.heading(col, text=col)
    treeview.column(col, width=120)

treeview.pack(side="left", fill="both", expand=True)

scrollbar = ttk.Scrollbar(frame, orient="vertical", command=treeview.yview)
scrollbar.pack(side="right", fill="y")
treeview.config(yscrollcommand=scrollbar.set)

button_frame = tk.Frame(window)
button_frame.pack(pady=10)

tk.Button(button_frame, text="Agregar artículo", command=add_item, width=20).pack(side="left", padx=10)
tk.Button(button_frame, text="Editar artículo", command=edit_item, width=20).pack(side="left", padx=10)
tk.Button(button_frame, text="Eliminar artículo", command=delete_item, width=20).pack(side="left", padx=10)
tk.Button(button_frame, text="Vender artículo", command=sell_item, width=20).pack(side="left", padx=10)
tk.Button(button_frame, text="Devolver artículo", command=return_item, width=20).pack(side="left", padx=10)

# -------------------------
# Inicialización
# -------------------------
API_KEY = simpledialog.askstring("Clave API", "Introduce la clave API del servidor:")
if not API_KEY:
    messagebox.showerror("Error", "Se necesita la clave API para conectarse al servidor.")
    window.quit()

update_inventory_display()
window.after(10000, refresh_inventory)  # Llamar al refresco cada 10 segundos

window.mainloop()
