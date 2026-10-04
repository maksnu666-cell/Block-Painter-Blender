bl_info = {
    "name": "Block Paint",
    "author": "Switch",
    "version": (0, 1, 0),
    "blender": (5, 2, 0),
    "location": "3D View: Ctrl+Shift+B / панель N > Block Paint",
    "description": "Block Paint: 0.5 м XY-сетка и реальные Z-слои блоков",
    "category": "3D View",
}

import bpy
import math
from bpy_extras import view3d_utils
from mathutils import Vector, Matrix, geometry

AXES = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))


GRID_SIZE = 1

Z_KEY_STEP = 0.5


FRONT_OFFSET = 0

# Блоки, в названии которых есть это слово (любой регистр, в любом месте имени),
# ведут себя как лестницы в майнкрафте: снизу и на верхней половине боковой грани
# они ставятся перевёрнутыми. Остальные блоки никогда не переворачиваются.
STAIRS_TAG = "stair"

# Майнкрафтовское авто-переворачивание лестниц (низ блока / верхняя половина боковой
# грани = вверх ногами). Если хочешь, чтобы лестницы ВСЕГДА ставились как обычные
# блоки без переворота, поставь False.
STAIRS_AUTO_FLIP = True

# Угловая лестница (внешний угол, как в майнкрафте: плита + один угловой кубик сверху).
# Блок считается угловым, если в имени есть "stair" И одно из этих слов, например
# "stairsangle", "stairs_corner". Он сам определяет поворот и переворот по соседним
# обычным лестницам. Если соседей нет, ставится как обычная лестница (по взгляду).
CORNER_WORDS = ("angle", "corner")
CORNER_AUTO = True


def _rot_cardinal(v, yaw, flip):
  
    x, y = v
    if flip:
        x = -x
    for _ in range(yaw % 4):
        x, y = -y, x
    return (x, y)


def _flood_cells(blocked, start, limit=20000):
    
    if not blocked:
        return None, start
    x0 = min(c[0] for c in blocked); x1 = max(c[0] for c in blocked)
    y0 = min(c[1] for c in blocked); y1 = max(c[1] for c in blocked)
    if not (x0 <= start[0] <= x1 and y0 <= start[1] <= y1):
        return None, start
    seen = {start}
    stack = [start]
    while stack:
        cx, cy = stack.pop()
        for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if n in blocked or n in seen:
                continue
            if not (x0 <= n[0] <= x1 and y0 <= n[1] <= y1) or len(seen) >= limit:
                return None, (cx, cy)   # последняя клетка внутри контура = место дыры
            seen.add(n)
            stack.append(n)
    return seen, None


def _solve_corner_yaw(q0, flip, target):
    for yaw in range(4):
        if _rot_cardinal(q0, yaw, flip) == target:
            return yaw
    return None


def _add(c, o):
    return (c[0] + o[0], c[1] + o[1], c[2] + o[2])


def _neg(o):
    return (-o[0], -o[1], -o[2])


NAV_TYPES = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE',
             'WHEELOUTMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'HOME'}
HINT = ("Block Paint:  ЛКМ ставить | Ctrl+ЛКМ стереть | Shift+ЛКМ выбрать по одному | Alt+ЛКМ рамка по слою | "
        "Z размножить | C выемка | F залить | X удалить выбранное | Ctrl+Z отмена | Esc выход")


# ======================= данные и интерфейс =======================

class BP_Block(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(
        name="Блок", type=bpy.types.Object,
        poll=lambda self, o: o.type == 'MESH')


class BP_UL_blocks(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, "obj", text="")


class BP_OT_add_selected(bpy.types.Operator):
    
    bl_idname = "bpaint.add_selected"
    bl_label = "Добавить выбранные"

    def execute(self, context):
        sc = context.scene
        have = {b.obj for b in sc.bp_blocks if b.obj}
        objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not objs and context.active_object and context.active_object.type == 'MESH':
            objs = [context.active_object]
        for o in objs:
            if o not in have:
                it = sc.bp_blocks.add()
                it.obj = o
                have.add(o)
        return {'FINISHED'}


class BP_OT_remove(bpy.types.Operator):
    
    bl_idname = "bpaint.remove_block"
    bl_label = "Убрать"

    def execute(self, context):
        sc = context.scene
        if 0 <= sc.bp_index < len(sc.bp_blocks):
            sc.bp_blocks.remove(sc.bp_index)
            sc.bp_index = max(0, min(sc.bp_index, len(sc.bp_blocks) - 1))
        return {'FINISHED'}


class BP_PT_panel(bpy.types.Panel):
    bl_label = "Block Paint"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Block Paint"

    def draw(self, context):
        sc = context.scene
        lay = self.layout
        lay.operator("bpaint.run", text="Рисовать  (Ctrl+Shift+B)", icon='BRUSH_DATA')
        lay.label(text="Ассеты (выбери один активный):")
        row = lay.row()
        row.template_list("BP_UL_blocks", "", sc, "bp_blocks", sc, "bp_index", rows=4)
        col = row.column(align=True)
        col.operator("bpaint.add_selected", icon='ADD', text="")
        col.operator("bpaint.remove_block", icon='REMOVE', text="")
        box = lay.box()
        for t in ("Блоки сами поворачиваются лицом к тебе (по 90)",
                  "Имя с Stairs: снизу / верх грани - вверх ногами",
                  "Имя с Stairs+Angle: угловой блок сам встаёт по соседним лестницам",
                  "ЛКМ - рисовать один фиксированный слой",
                  "Новый слой: отпусти ЛКМ и нажми по верхней грани",
                  "Ctrl+ЛКМ - стирать",
                  "Shift+ЛКМ - выбирать по одному (Shift+Ctrl - снять)",
                  "Alt+ЛКМ - рамка: выбирает один слой, насквозь не берёт",
                  "Alt+Shift+ЛКМ - выбрать весь слой целиком",
                  "(Alt+Ctrl - то же, но снимает выбор)",
                  "Z - размножить выбранное, ведёшь мышь",
                  "  потом X / Y / Z - зафиксировать ось",
                  "C - выемка: ведёшь мышь, блоки удаляются",
                  "F - залить замкнутую область",
                  "X - удалить выбранное",
                  "A / Alt+A - выбрать всё / снять",
                  "Ctrl+Z / Ctrl+Shift+Z - отмена / возврат"):
            box.label(text=t)


# ======================= сам инструмент =======================

class BP_OT_run(bpy.types.Operator):
    
    bl_idname = "bpaint.run"
    bl_label = "Block Paint"

    # ---------- запуск ----------
    def invoke(self, context, event):
        area = context.area
        if area is None or area.type != 'VIEW_3D':
            return {'CANCELLED'}
        sc = context.scene

        palette = [b.obj for b in sc.bp_blocks if b.obj and b.obj.type == 'MESH']
        self.fallback = None
        tmpls = list(palette)
        if not tmpls:
            a = context.active_object
            if a and a.type == 'MESH':
                self.fallback = a
                tmpls = [a]
            else:
                self.report({'ERROR'}, "Добавь блоки в палитру (панель N > Block Paint) или выбери куб")
                return {'CANCELLED'}

        # The palette's active row is the ONLY asset used for painting.
        self.selected_template = None
        if 0 <= int(sc.bp_index) < len(sc.bp_blocks):
            candidate = sc.bp_blocks[int(sc.bp_index)].obj
            if candidate is not None and candidate.type == 'MESH':
                self.selected_template = candidate
        if self.selected_template is None:
            self.selected_template = tmpls[0]

        self.scene = sc
        self.area = area
        self.region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        self.rv3d = area.spaces.active.region_3d
        if self.region is None or self.rv3d is None:
            return {'CANCELLED'}

        # Проектная сетка всегда 0.5 м.
        # ВАЖНО: GRID_SIZE не является размером блока.
        # Блоки могут иметь любые габариты; их реальные грани используются
        # при стыковке, а XY-позиционирование остаётся привязанным к 0.5 м.
        self.grid_size = GRID_SIZE
        self.size = self.grid_size  # совместимость со старой логикой UI/selection
        self.origin = Vector((0.0, 0.0, 0.0))
        self.mesh_to_tmpl = {t.data.name: t for t in tmpls}
        self.tnames = {t.name for t in tmpls}

        # Объекты, которые Block Paint уже создал, помечаются специальным
        # свойством. Это критично: после ESC оператор уничтожается, и при
        # следующем запуске self.cells собирается заново. Раньше новые блоки
        # имели отдельный Mesh, но здесь искались только по data.name шаблона,
        # поэтому после повторного входа они "исчезали" для инструмента.
        self.cells = {}
        for ob in sc.objects:
            if ob.type != 'MESH':
                continue

            is_template = ob.name in self.tnames
            is_generated = bool(ob.get("bp_generated", False))
            template_data = ob.get("bp_template_data")

            # Основной новый формат: generated-блок знает, из какого шаблона
            # он был сделан, даже если его Mesh уже уникальный/изменён в Edit Mode.
            is_known = (ob.data and ob.data.name in self.mesh_to_tmpl) or is_generated

            # Совместимость со старыми блоками, созданными до этой метки:
            # если это отдельный объект кубического размера и его геометрический
            # центр лежит на нашей сетке — считаем его блоком.
            legacy = False
            if not is_known and not is_template:
                d = Vector(ob.dimensions)
                legacy = (abs(d.x - self.size) < 1e-4 and
                          abs(d.y - self.size) < 1e-4 and
                          abs(d.z - self.size) < 1e-4 and
                          self.on_grid(ob))

            if not (is_known or legacy):
                continue

            if is_template and not self.on_grid(ob):
                continue  # сам шаблон вне нашей сетки — не часть острова

            cell = self.cell_of(ob)
           
            if is_generated:
                ob["bp_cell_valid"] = True
                ob["bp_cell_x"], ob["bp_cell_y"], ob["bp_cell_z"] = cell

            # Не позволяем двум объектам занимать одну логическую клетку.
            # Если там уже есть generated-блок, оставляем его; иначе первый.
            if cell not in self.cells:
                self.cells[cell] = ob

            # Однократно мигрируем старые блоки в новый формат. После этого
            # им больше не важно, как называется их Mesh и где находится его
            # геометрический центр.
            if legacy and cell in self.cells and self.cells[cell] == ob:
                t = self._template_for_legacy(ob)
                ob["bp_generated"] = True
                ob["bp_cell_valid"] = True
                ob["bp_cell_x"], ob["bp_cell_y"], ob["bp_cell_z"] = cell
                if t is not None:
                    ob["bp_template_data"] = t.data.name if t.data else ""
                    ob["bp_template_name"] = t.name

        self.painting = self.erasing = self.selecting = self.boxsel = False
        self.sel_remove = False
        self.mode = None
        self.selected = set()
        self.last = None
        self.dirty = True
        self.history, self.redo = [], []
        self.cur = {"add": [], "erase": []}
        self.mouse = Vector((0, 0))
        self.anchor = Vector((0, 0))
        self.ex_layers = []
        self.ex_axis = None
        self.ex_sign = 1
        self.paint_plane_z = 0.0
        self.paint_z_layer = 0
        self.paint_support = None
        self.paint_support_axis = None
        self.paint_support_sign = 1
        self.paint_bottom_z = 0.0
        self.paint_start_cell = (0, 0, 0)
        # Реальные габариты (AABB) каждого блока: нужны, чтобы новый блок физически
        # не залезал в соседние, даже если ключи клеток у них разные.
        self.aabb = {}
        self.max_dim = max([max(self.template_dimensions_world(t)) for t in tmpls] + [self.grid_size])
        self.cur_q = 0            # поворот новых блоков: 0..3 четверти по 90 градусов
        self.cur_flip = False     # перевернуть лестницу (ставится снизу / на верхнюю половину грани)
        self.hit_flip = False
        self.block_info = {}      # клетка -> (центр, поворот): чтобы отмена возвращала блок точно
        self.ex_items = []

        for ob in list(context.selected_objects):
            ob.select_set(False)

        area.header_text_set(HINT)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    # ---------- геометрия ----------
    def block_center(self, ob):
        """Мировой центр геометрии блока, а не его origin.
        Это важно для ассетов, у которых origin не находится в центре меша.
        """
        bb = [Vector(c) for c in ob.bound_box]
        local_center = sum(bb, Vector()) / 8.0
        return ob.matrix_world @ local_center

    def on_grid(self, ob):
        
        d = self.block_center(ob) / self.grid_size
        return all(abs(v - round(v)) < 1e-3 for v in d)

    def _z_key_from_height(self, z):
      
        return int(round(float(z) / Z_KEY_STEP))

    def cell_of(self, ob):
        
        if ob is None:
            return (0, 0, 0)

        center = self.block_center(ob)
        x = int(round(center.x / self.grid_size))
        y = int(round(center.y / self.grid_size))
        lo, hi = self.block_bounds_world(ob)
        z = self._z_key_from_height(lo.z)
        return (x, y, z)

    def block_bounds_world(self, ob):
        bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        lo = Vector((min(p.x for p in bb), min(p.y for p in bb), min(p.z for p in bb)))
        hi = Vector((max(p.x for p in bb), max(p.y for p in bb), max(p.z for p in bb)))
        return lo, hi

    def block_dimensions_world(self, ob):
        lo, hi = self.block_bounds_world(ob)
        return hi - lo

    def template_dimensions_world(self, tmpl):
        if tmpl is None:
            return Vector((self.grid_size, self.grid_size, self.grid_size))
        lo, hi = self.block_bounds_world(tmpl)
        return hi - lo

    def block_footprint_xy(self, ob):
        lo, hi = self.block_bounds_world(ob)
        return lo.x, hi.x, lo.y, hi.y

    def _snap_xy(self, value):
        return math.floor(value / self.grid_size + 0.5) * self.grid_size

    def _template_center_offset(self, tmpl):
        # World-space center of the template's geometry relative to its origin.
        return self.block_center(tmpl) - tmpl.location

    def _template_world_size(self, tmpl):
        lo, hi = self.block_bounds_world(tmpl)
        return hi - lo

    def _candidate_support_face(self, ob, axis, sign):
        lo, hi = self.block_bounds_world(ob)
        return hi[axis] if sign > 0 else lo[axis]

    def view_quarter(self):
        """Куда смотрит игрок, округлённо до 4 сторон. 0 = смотрит вдоль +Y (как шаблон).
        Если камера смотрит почти вертикально, берём направление "верха экрана",
        поэтому высоко поднятая камера не даёт наклонов вроде 45 градусов."""
        q = self.rv3d.view_rotation
        fwd = q @ Vector((0, 0, -1))
        up = q @ Vector((0, 1, 0))
        h = Vector((fwd.x, fwd.y))
        if h.length < 0.35:
            h = Vector((up.x, up.y)) if fwd.z < 0 else Vector((-up.x, -up.y))
        if h.length < 1e-6:
            return FRONT_OFFSET % 4
        ang = math.atan2(h.y, h.x) - math.pi / 2.0
        return (int(round(ang / (math.pi / 2.0))) + FRONT_OFFSET) % 4

    def is_stairs(self, tmpl):
        return tmpl is not None and STAIRS_TAG in tmpl.name.lower()

    def is_corner(self, tmpl):
        if not self.is_stairs(tmpl):
            return False
        name = tmpl.name.lower()
        return any(w in name for w in CORNER_WORDS)

    def _shape_of(self, tmpl):
        """Определить форму шаблона по самой геометрии (а не по предположениям):
        ('stairs', (dx, dy)) - в какую сторону смотрит высокая часть лестницы;
        ('corner', (qx, qy)) - в каком углу стоит верхний кубик углового блока."""
        if tmpl is None or not self.is_stairs(tmpl) or tmpl.data is None:
            return None
        cache = getattr(self, "_shape_cache", None)
        if cache is None:
            cache = {}
            self._shape_cache = cache
        if tmpl.name in cache:
            return cache[tmpl.name]
        res = None
        try:
            lo, hi = self.block_bounds_world(tmpl)
            c = (lo + hi) / 2.0
            size = hi - lo
            mw = tmpl.matrix_world
            pts = [mw @ v.co for v in tmpl.data.vertices]
            ztop = max(p.z for p in pts)
            top = [p for p in pts if p.z > ztop - 1e-4]
            ox = sum(p.x for p in top) / len(top) - c.x
            oy = sum(p.y for p in top) / len(top) - c.y
            tx, ty = 0.05 * size.x, 0.05 * size.y
            ax, ay = abs(ox), abs(oy)
            if self.is_corner(tmpl):
                if ax > tx and ay > ty:
                    res = ('corner', (1 if ox > 0 else -1, 1 if oy > 0 else -1))
            else:
                if ax > tx and ay <= ax * 0.5:
                    res = ('stairs', (1 if ox > 0 else -1, 0))
                elif ay > ty and ax <= ay * 0.5:
                    res = ('stairs', (0, 1 if oy > 0 else -1))
        except Exception:
            res = None
        cache[tmpl.name] = res
        return res

    def block_at_point(self, p):
        """Блок, чей габаритный бокс содержит точку p (или None)."""
        eps = 1e-3
        r = int(math.ceil(self.max_dim / self.grid_size)) + 1
        rz = int(math.ceil(self.max_dim / Z_KEY_STEP)) + 2
        cx = int(round(p.x / self.grid_size))
        cy = int(round(p.y / self.grid_size))
        cz = self._z_key_from_height(p.z)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-rz, rz + 1):
                    key = (cx + dx, cy + dy, cz + dz)
                    ob = self.cells.get(key)
                    if ob is None:
                        continue
                    lo, hi = self.aabb_for(key, ob)
                    if (lo[0] - eps < p.x < hi[0] + eps and lo[1] - eps < p.y < hi[1] + eps
                            and lo[2] - eps < p.z < hi[2] + eps):
                        return ob
        return None

    def corner_orientation(self, tmpl, center, size, hint_flip):
        """Правило майнкрафта для внешнего угла: сосед в стороне a, у которого высокая
        часть смотрит в f (перпендикулярно a), даёт угловой кубик в углу a+f.
        Возвращает (yaw, flip) или None, если подходящих лестниц рядом нет."""
        sh = self._shape_of(tmpl)
        if not sh or sh[0] != 'corner':
            return None
        q0 = sh[1]
        votes = {}
        for a in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = Vector((center.x + a[0] * (size.x / 2.0 + 0.01),
                        center.y + a[1] * (size.y / 2.0 + 0.01),
                        center.z))
            ob = self.block_at_point(p)
            if ob is None:
                continue
            nsh = self._shape_of(self.tmpl_of(ob))
            if not nsh or nsh[0] != 'stairs':
                continue
            nflip = bool(ob.get("bp_flip", 0))
            f = _rot_cardinal(nsh[1], int(ob.get("bp_yaw", 0)), nflip)
            if f[0] * a[0] + f[1] * a[1] != 0:
                continue          # смотрит вдоль линии к углу - не угловой случай
            key = ((a[0] + f[0], a[1] + f[1]), nflip)
            votes[key] = votes.get(key, 0) + 1
        if not votes:
            return None
        (q, fl), _n = max(votes.items(), key=lambda kv: (kv[1], kv[0][1] == bool(hint_flip)))
        yaw = _solve_corner_yaw(q0, fl, q)
        if yaw is None:
            return None
        return yaw, fl

    def key_of(self, ob):
        """Ключ клетки объекта. Берём запомненный при создании, а не пересчитываем."""
        if ob is not None and ob.get("bp_cell_valid", False):
            try:
                return (int(ob["bp_cell_x"]), int(ob["bp_cell_y"]), int(ob["bp_cell_z"]))
            except Exception:
                pass
        return self.cell_of(ob)

    def key_for_center(self, center, size_z):
        return (int(round(center.x / self.grid_size)),
                int(round(center.y / self.grid_size)),
                self._z_key_from_height(center.z - size_z / 2.0))

    def mouse_pos(self, event):
        return Vector((event.mouse_x - self.region.x, event.mouse_y - self.region.y))

    def in_view(self, event):
        r = self.region
        mx, my = event.mouse_x, event.mouse_y
        if not (r.x <= mx < r.x + r.width and r.y <= my < r.y + r.height):
            return False
        for o in self.area.regions:  # боковая панель, тулбар и т.п. поверх вьюпорта
            if o.type != 'WINDOW' and o.width > 1 and o.height > 1 \
                    and o.x <= mx < o.x + o.width and o.y <= my < o.y + o.height:
                return False
        # навигационные оси (гизмо) справа сверху: клики по ним отдаём Blender
        prefs = bpy.context.preferences
        s = max(prefs.view.ui_scale, 0.5) * prefs.system.dpi / 72.0
        right = r.x + r.width
        for o in self.area.regions:
            if o.type == 'UI' and o.width > 1:
                right -= o.width
        top = r.y + r.height
        if right - 125 * s <= mx < right and top - 310 * s <= my < top:
            return False
        return True

    def ray(self, event):
        c = self.mouse_pos(event)
        o = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, c)
        v = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, c)
        return o, v

    def _canonical_hit(self, hit, event):
        """Привести попадание к ГРАНИ КЛЕТКИ (габаритному боксу блока).

        У лестницы меш не кубический: луч попадает во внутренние грани (ступенька,
        подступенок) или даже в обратную сторону грани, и нормаль меша указывает
        не туда, куда смотрит внешняя грань клетки. Из-за этого блок ставился
        "сквозь" лестницу, с другой стороны. Поэтому для ВСЕХ блоков сторона
        определяется тем, через какую грань бокса блока луч входит в него, то есть
        ровно как у обычного куба. Для кубов результат тот же, что и раньше."""
        ob, nor, loc = hit
        o, v = self.ray(event)
        lo, hi = self.block_bounds_world(ob)
        eps = 1e-4
        t_near, t_far = -1e18, 1e18
        face_axis = None
        for a in range(3):
            if abs(v[a]) < 1e-9:
                if o[a] < lo[a] - eps or o[a] > hi[a] + eps:
                    t_near, t_far = 1.0, 0.0   # промах
                    break
                continue
            t1 = (lo[a] - o[a]) / v[a]
            t2 = (hi[a] - o[a]) / v[a]
            if t1 > t2:
                t1, t2 = t2, t1
            if t1 > t_near:
                t_near, face_axis = t1, a
            t_far = min(t_far, t2)
        if face_axis is not None and t_near <= t_far + 1e-6 and t_far > 0.0 and t_near > 0.0:
            n = Vector((0, 0, 0))
            n[face_axis] = -1.0 if v[face_axis] > 0 else 1.0
            return ob, n, o + v * t_near
        # Скользящий луч мимо бокса: берём нормаль меша, но всегда лицом к камере.
        n = Vector(nor)
        if n.dot(v) > 0:
            n = -n
        return ob, n, loc

    def raycast_block(self, event):
        hit = self._raycast_block_raw(event)
        if hit is None:
            return None
        return self._canonical_hit(hit, event)

    def _raycast_block_raw(self, event):
        """Raycast only generated Block Paint blocks, never source assets."""
        if self.dirty:
            bpy.context.view_layer.update()
            self.dirty = False

        origin, direction = self.ray(event)
        depsgraph = bpy.context.evaluated_depsgraph_get()

        for _ in range(64):
            ok, loc, nor, idx, ob, mat = self.scene.ray_cast(depsgraph, origin, direction)
            if not ok or ob is None:
                return None
            ob = ob.original
            if ob.type == 'MESH':
                # A placed block is identified by its own immutable marker.
                # Do NOT require cell_of(ob) to reproduce the exact dictionary
                # key here: with 0.25m plates, floating-point bounds and mixed
                # block heights can make the reconstructed key differ by one
                # rounding unit even though the object is perfectly valid.
                # That used to make visible side faces randomly "invisible".
                if ob.get("bp_generated", False) and ob.name not in self.tnames:
                    return ob, nor, loc
            origin = loc + direction * 1e-4
        # If Blender's ray missed a very thin/edge-on generated face, do one
        # conservative screen-space fallback. It only accepts a generated
        # object's projected bounding box when the mouse is within a few pixels
        # of that box, so it cannot suddenly select a distant asset or spawn on
        # the world grid.
        mouse = self.mouse_pos(event)
        best = None
        best_d2 = 9.0 * 9.0
        for ob in self.cells.values():
            if ob is None or not ob.get("bp_generated", False):
                continue
            try:
                pts = [view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, ob.matrix_world @ Vector(c))
                       for c in ob.bound_box]
                pts = [p for p in pts if p is not None]
                if not pts:
                    continue
                minx = min(p.x for p in pts); maxx = max(p.x for p in pts)
                miny = min(p.y for p in pts); maxy = max(p.y for p in pts)
                dx = 0.0 if minx <= mouse.x <= maxx else min(abs(mouse.x-minx), abs(mouse.x-maxx))
                dy = 0.0 if miny <= mouse.y <= maxy else min(abs(mouse.y-miny), abs(mouse.y-maxy))
                d2 = dx*dx + dy*dy
                if d2 < best_d2:
                   
                    center = self.block_center(ob)
                    ro, rv = self.ray(event)
                    to_center = center - ro
                    if to_center.dot(rv) <= 0:
                        continue
                    best = ob
                    best_d2 = d2
            except Exception:
                continue
        if best is not None:
            ro, rv = self.ray(event)
            # Choose the closest AABB face to the ray for a deterministic normal.
            lo, hi = self.block_bounds_world(best)
            center = self.block_center(best)
            axis = max(range(3), key=lambda a: abs(rv[a]))
            sign = -1 if rv[axis] > 0 else 1
            loc = center.copy()
            loc[axis] = hi[axis] if sign > 0 else lo[axis]
            nor = Vector((0, 0, 0)); nor[axis] = sign
            return best, nor, loc
        return None

    def _target_from_hit(self, hit):
        """Build the FIRST cell of a stroke from the actual face hit."""
        ob, nor, hit_loc = hit
        axis = max(range(3), key=lambda a: abs(nor[a]))
        sign = 1 if nor[axis] > 0 else -1

       
        c = self.block_center(ob)
        x = int(round(c.x / self.grid_size))
        y = int(round(c.y / self.grid_size))
        lo, hi = self.block_bounds_world(ob)

        # Правила майнкрафта: низ блока или ВЕРХНЯЯ половина боковой грани = перевёрнутая
        # лестница; верх блока или нижняя половина боковой грани = обычная.
        if axis == 2:
            self.hit_flip = sign < 0
        else:
            self.hit_flip = hit_loc.z > (lo.z + hi.z) / 2.0 + 1e-6
        if not STAIRS_AUTO_FLIP:
            self.hit_flip = False

        if axis == 2:
            # Start the next layer exactly on the real face.
            plane_z = hi.z if sign > 0 else lo.z
            if sign > 0:
                z = self._z_layer_from_face(plane_z, sign)
            else:
                # Вниз: новый блок висит ПОД опорой, его низ = грань минус высота блока.
                # Раньше ключ совпадал с ключом самой опоры, клетка считалась занятой
                # и блок просто не ставился.
                h = self.template_dimensions_world(self.pick_template()).z
                z = self._z_key_from_height(plane_z - h)
            return (x, y, z), 2, sign, ob, plane_z

        if axis == 0:
            x += sign
        else:
            y += sign

        
        plane_z = lo.z
        z = self._z_key_from_height(plane_z)
        return (x, y, z), axis, sign, ob, plane_z

    def _world_target_from_event(self, event, plane_z, layer_z):
        """Project the mouse onto one fixed horizontal drawing plane."""
        o, v = self.ray(event)
        if abs(v.z) < 1e-7:
            return None
        t = (plane_z - o.z) / v.z
        if t < 0:
            return None
        p = o + v * t
        x = int(math.floor(p.x / self.grid_size + 0.5))
        y = int(math.floor(p.y / self.grid_size + 0.5))
        self.hit_flip = False
        return (x, y, layer_z), 2, 1, None, plane_z

    def target_from_click(self, event):
        hit = self.raycast_block(event)
        if hit:
            return self._target_from_hit(hit)
        # Empty world always starts on the ground plane.
        return self._world_target_from_event(event, 0.0, 0)

    def _z_layer_from_face(self, face_z, sign):
        # Logical ID only. Physical placement uses the exact face_z.
        # The key has 0.25m resolution so a 0.25m plate stack gets unique
        # identities at 0.00 / 0.25 / 0.50 / 0.75 / ... without changing the
        # actual project placement grid (which remains 0.5m in X/Y).
        return self._z_key_from_height(face_z)

    def _paint_target_from_event(self, event):
        # During a stroke existing blocks are ignored. The layer was locked
        # when LMB was pressed, so the brush cannot climb or fall by itself.
        return self._world_target_from_event(event, self.paint_plane_z, self.paint_z_layer)

    # ---------- блоки ----------
    def _template_for_legacy(self, ob):
        """Найти шаблон для legacy-блока по реальным размерам."""
        if ob is None:
            return None
        d = self.block_dimensions_world(ob)
        best = None
        best_err = float("inf")
        for t in self.mesh_to_tmpl.values():
            td = self.template_dimensions_world(t)
            err = sum(abs(d[a] - td[a]) for a in range(3))
            if err < best_err:
                best_err = err
                best = t
        return best

    def tmpl_of(self, ob):
        if ob is None or ob.type != 'MESH':
            return None

        # Сначала смотрим сохранённую ссылку на шаблон. Она переживает
        # независимое копирование Mesh и повторный вход в инструмент.
        template_data = ob.get("bp_template_data")
        if template_data:
            t = self.mesh_to_tmpl.get(template_data)
            if t is not None:
                return t

        # Шаблон или старый объект, который всё ещё использует Mesh шаблона.
        t = self.mesh_to_tmpl.get(ob.data.name)
        if t is not None:
            return t

        # Legacy-блоки: выбираем шаблон с ближайшими реальными габаритами.
        d = self.block_dimensions_world(ob)
        best = None
        best_err = float("inf")
        for t in self.mesh_to_tmpl.values():
            td = self.template_dimensions_world(t)
            err = sum(abs(d[a] - td[a]) for a in range(3))
            if err < best_err:
                best_err = err
                best = t
        return best

    def pick_template(self):
        """Return exactly the asset selected in the Block Paint palette.

        There is deliberately NO random mixing here. The active palette row
        (Scene.bp_index) is the only source used for new blocks.
        """
        items = self.scene.bp_blocks
        idx = int(self.scene.bp_index)
        if 0 <= idx < len(items):
            t = items[idx].obj
            if t is not None and t.type == 'MESH':
                self.mesh_to_tmpl.setdefault(t.data.name, t)
                self.tnames.add(t.name)
                return t

        return self.selected_template or self.fallback

    def aabb_for(self, cell, ob):
        bb = self.aabb.get(cell)
        if bb is None:
            lo, hi = self.block_bounds_world(ob)
            bb = ((lo.x, lo.y, lo.z), (hi.x, hi.y, hi.z))
            self.aabb[cell] = bb
        return bb

    def overlaps(self, center, size):
        """Есть ли физическое пересечение с уже стоящими блоками.
        Касание гранями - не пересечение. Ключи клеток тут не важны."""
        eps = 1e-3
        lo = (center.x - size.x / 2.0, center.y - size.y / 2.0, center.z - size.z / 2.0)
        hi = (center.x + size.x / 2.0, center.y + size.y / 2.0, center.z + size.z / 2.0)
        r = int(math.ceil(max(self.max_dim, size.x, size.y) / self.grid_size)) + 1
        rz = int(math.ceil(max(self.max_dim, size.z) / Z_KEY_STEP)) + 2
        cx = int(round(center.x / self.grid_size))
        cy = int(round(center.y / self.grid_size))
        cz = self._z_key_from_height(center.z)
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-rz, rz + 1):
                    key = (cx + dx, cy + dy, cz + dz)
                    ob = self.cells.get(key)
                    if ob is None:
                        continue
                    olo, ohi = self.aabb_for(key, ob)
                    if (lo[0] < ohi[0] - eps and hi[0] > olo[0] + eps and
                            lo[1] < ohi[1] - eps and hi[1] > olo[1] + eps and
                            lo[2] < ohi[2] - eps and hi[2] > olo[2] + eps):
                        return True
        return False

    def make_block(self, cell, tmpl, support_ob=None, support_axis=None, support_sign=1,
                   placement_z=None, center=None, yaw=None, flip=None):
        """Создаёт блок. Возвращает ключ клетки или None, если создать нельзя.
        center - точный мировой центр (для экструда/отмены), yaw - четверти по 90 градусов."""
        if tmpl is None:
            return None
        yaw = (self.cur_q if yaw is None else int(yaw)) % 4
        flip = bool(self.cur_flip) if flip is None else bool(flip)
        if not self.is_stairs(tmpl):
            flip = False

        tmpl_lo, tmpl_hi = self.block_bounds_world(tmpl)
        tmpl_size = tmpl_hi - tmpl_lo
        if yaw % 2 == 1:      # поворот на 90/270: ширина и глубина меняются местами
            tmpl_size = Vector((tmpl_size.y, tmpl_size.x, tmpl_size.z))

        if center is not None:
            desired_center = Vector(center)
        else:
            desired_x = cell[0] * self.grid_size
            desired_y = cell[1] * self.grid_size
            desired_bottom_z = 0.0

            if support_ob is not None and support_axis is not None:
                s_lo, s_hi = self.block_bounds_world(support_ob)
                sc = self.block_center(support_ob)

                if support_axis == 2:
                    if support_sign > 0:
                        desired_bottom_z = s_hi.z
                    else:
                        desired_bottom_z = s_lo.z - tmpl_size.z
                    desired_x = round(sc.x / self.grid_size) * self.grid_size
                    desired_y = round(sc.y / self.grid_size) * self.grid_size

                elif support_axis == 0:
                    if support_sign > 0:
                        desired_x = s_hi.x + tmpl_size.x / 2.0
                    else:
                        desired_x = s_lo.x - tmpl_size.x / 2.0
                    desired_y = round(sc.y / self.grid_size) * self.grid_size
                    desired_bottom_z = s_lo.z

                elif support_axis == 1:
                    if support_sign > 0:
                        desired_y = s_hi.y + tmpl_size.y / 2.0
                    else:
                        desired_y = s_lo.y - tmpl_size.y / 2.0
                    desired_x = round(sc.x / self.grid_size) * self.grid_size
                    desired_bottom_z = s_lo.z

            elif placement_z is not None:
                desired_bottom_z = placement_z

            desired_center = Vector((desired_x, desired_y, desired_bottom_z + tmpl_size.z / 2.0))

        # Угловая лестница: поворот и переворот берём у соседних лестниц.
        if center is None and CORNER_AUTO and self.is_corner(tmpl):
            auto = self.corner_orientation(tmpl, desired_center, tmpl_size, flip)
            if auto is not None:
                new_yaw, flip = auto
                if (new_yaw - yaw) % 2:   # 90/270: ширина и глубина меняются местами
                    tmpl_size = Vector((tmpl_size.y, tmpl_size.x, tmpl_size.z))
                yaw = new_yaw

        # Ключ всегда считаем из реального положения, поэтому он совпадает с cell_of().
        cell = self.key_for_center(desired_center, tmpl_size.z)
        if cell in self.cells:
            return None
        if self.overlaps(desired_center, tmpl_size):
            return None   # блок не проходит сквозь другие

        new = tmpl.copy()
        if tmpl.data is not None:
            new.data = tmpl.data.copy()

        new["bp_generated"] = True
        new["bp_template_data"] = tmpl.data.name if tmpl.data else ""
        new["bp_template_name"] = tmpl.name
        new["bp_cell_valid"] = True
        new["bp_cell_x"], new["bp_cell_y"], new["bp_cell_z"] = cell
        new["bp_yaw"] = yaw
        new["bp_flip"] = int(flip)

        # Поворот вокруг Z поверх поворота шаблона (лицом к игроку).
        r_old = tmpl.matrix_world.to_3x3().normalized()
        r_new = r_old
        if flip:
            # Кувырок на 180 градусов вокруг оси лестницы (Y шаблона): ступенька уходит
            # наверх, а "спинка" остаётся с той же стороны, как в майнкрафте.
            r_new = Matrix.Rotation(math.pi, 3, 'Y') @ r_new
        r_new = Matrix.Rotation(yaw * math.pi / 2.0, 3, 'Z') @ r_new
        new.rotation_mode = 'XYZ'
        new.rotation_euler = r_new.to_euler('XYZ')

        # Центр геометрии (а не origin) ставим ровно в desired_center.
        bb = [Vector(c) for c in new.bound_box]
        local_center = sum(bb, Vector()) / 8.0
        world_offset = (r_new @ Matrix.Diagonal(new.scale)) @ local_center
        new.location = desired_center - world_offset

        coll = tmpl.users_collection[0] if tmpl.users_collection else self.scene.collection
        coll.objects.link(new)
        self.cells[cell] = new
        self.block_info[cell] = (tuple(desired_center), yaw, int(flip))
        self.aabb[cell] = ((desired_center.x - tmpl_size.x / 2.0, desired_center.y - tmpl_size.y / 2.0,
                            desired_center.z - tmpl_size.z / 2.0),
                           (desired_center.x + tmpl_size.x / 2.0, desired_center.y + tmpl_size.y / 2.0,
                            desired_center.z + tmpl_size.z / 2.0))
        self.max_dim = max(self.max_dim, tmpl_size.x, tmpl_size.y, tmpl_size.z)
        self.dirty = True
        return cell

    def restore_block(self, cell, tmpl):
        """Вернуть удалённый блок на то же место с тем же поворотом."""
        info = self.block_info.get(cell)
        if info:
            return self.make_block(cell, tmpl, center=Vector(info[0]), yaw=info[1], flip=bool(info[2]))
        return self.make_block(cell, tmpl)

    def _find_support_for_cell(self, cell):
        # Find an existing block occupying the nearest project-grid neighbor.
        # Preference is given to vertical support, then X/Y neighbors.
        x, y, z = cell

        candidates = [
            ((x, y, z - 1), 2, 1),
            ((x, y, z + 1), 2, -1),
            ((x - 1, y, z), 0, 1),
            ((x + 1, y, z), 0, -1),
            ((x, y - 1, z), 1, 1),
            ((x, y + 1, z), 1, -1),
        ]

        for nc, axis, sign in candidates:
            ob = self.cells.get(nc)
            if ob is not None:
                return ob, axis, sign
        return None

    def remove_block(self, cell):
        ob = self.cells.get(cell)
        if ob is None or ob.name in self.tnames:  # шаблоны не удаляем
            return False
        if cell not in self.block_info:   # у блоков из сцены; у наших точные данные уже есть
            self.block_info[cell] = (tuple(self.block_center(ob)), int(ob.get("bp_yaw", 0)),
                                     int(ob.get("bp_flip", 0)))
        self.aabb.pop(cell, None)
        del self.cells[cell]
        self.selected.discard(cell)
        bpy.data.objects.remove(ob, do_unlink=True)
        self.dirty = True
        return True

    def put(self, cell, support_ob=None, support_axis=None, support_sign=1, placement_z=None):
        t = self.pick_template()
        key = self.make_block(cell, t, support_ob, support_axis, support_sign, placement_z)
        if key:
            self.cur["add"].append((key, t))

    def commit_cur(self):
        if self.cur["add"] or self.cur["erase"]:
            self.history.append(self.cur)
            self.redo.clear()
            bpy.ops.ed.undo_push(message="Block Paint")
        self.cur = {"add": [], "erase": []}

    # ---------- отмена внутри режима ----------
    def undo_step(self):
        if not self.history:
            return
        op = self.history.pop()
        for c, t in op["add"]:
            self.remove_block(c)
        for c, t in op["erase"]:
            self.restore_block(c, t)
        self.redo.append(op)
        bpy.ops.ed.undo_push(message="Block Paint Undo")

    def redo_step(self):
        if not self.redo:
            return
        op = self.redo.pop()
        for c, t in op["add"]:
            self.restore_block(c, t)
        for c, t in op["erase"]:
            self.remove_block(c)
        self.history.append(op)
        bpy.ops.ed.undo_push(message="Block Paint Redo")

    # ---------- рисование ----------
    def begin_paint(self, event):
        t = self.target_from_click(event)
        if not t:
            return
        cell, axis, sign, support_ob, face_z = t
        self.cur_q = self.view_quarter()   # блоки смотрят лицом на игрока
        self.cur_flip = self.hit_flip      # лестницы: снизу / верхняя половина грани = перевёрнуты
        self.axis, self.sign = axis, sign
        self.fixed = cell[axis]
        self.painting = True
        self.last = None
        self.anchor = self.mouse.copy()

        # One LMB drag = exactly one horizontal layer.
        bottom_z = face_z
        if axis == 2 and sign < 0:   # вниз: низ нового слоя = грань минус высота блока
            bottom_z = face_z - self.template_dimensions_world(self.pick_template()).z
        self.paint_plane_z = face_z       # плоскость, на которую проецируем мышь
        if axis != 2:
            # Старт с боковой грани: плоскость рисования на середине высоты нового
            # блока. Раньше она была на уровне низа опоры, и луч от курсора, пройдя
            # через опору, попадал в клетку ЗА блоком - отсюда блоки "с другой стороны".
            self.paint_plane_z = bottom_z + self.template_dimensions_world(self.pick_template()).z / 2.0
        self.paint_start_cell = cell
        self.paint_bottom_z = bottom_z    # физический низ блоков этого мазка
        self.paint_z_layer = cell[2]
        self.paint_support = support_ob
        self.paint_support_axis = axis
        self.paint_support_sign = sign
        self.stroke(cell, support_ob, axis, sign, bottom_z)

    def stroke(self, cell, support_ob=None, support_axis=None, support_sign=1, placement_z=None):
        if self.last is None:
            self.put(cell, support_ob, support_axis, support_sign, placement_z)
            self.last = cell
            return

        d = [cell[a] - self.last[a] for a in range(3)]
        jump = max(abs(x) for x in d)

        # Never accept a huge/invalid jump. A near-parallel view or a bad
        # projection must NOT spawn a block thousands of cells away.
        if jump > 16:
            return

        steps = max(jump, 1)
        for s in range(1, steps + 1):
            c = tuple(round(self.last[a] + d[a] * s / steps) for a in range(3))
            # Only the first target has a known support face. Intermediate
            # cells continue on the fixed stroke plane.
            self.put(c, None, None, 1, placement_z)
        self.last = cell

    def erase_at(self, event):
        hit = self.raycast_block(event)
        if not hit:
            return
        ob = hit[0]
        cell = self.key_of(ob)
        t = self.tmpl_of(ob)
        if t is not None and self.remove_block(cell):
            self.cur["erase"].append((cell, t))

    # ---------- выделение ----------
    def select_cell(self, cell, state):
        ob = self.cells.get(cell)
        if ob is None:
            return
        try:
            ob.select_set(state)
        except RuntimeError:
            return
        if state:
            self.selected.add(cell)
        else:
            self.selected.discard(cell)

    def clear_selection(self):
        for c in list(self.selected):
            self.select_cell(c, False)

    # ---------- рамка по одному слою (Alt+ЛКМ) ----------
    def begin_box(self, event, whole):
        hit = self.raycast_block(event)
        if hit:
            ob, nor, hit_loc = hit
            axis = max(range(3), key=lambda a: abs(nor[a]))
            fs = 1 if nor[axis] > 0 else -1
            layer = self.key_of(ob)[axis]
        else:
            axis, fs, layer = 2, -1, 0   # земля
        self.box_axis, self.box_fs, self.box_layer = axis, fs, layer
        self.box_cells = [c for c in self.cells if c[axis] == layer]
        self.box_base = set(self.selected)
        self.box_start = self.mouse_pos(event)
        self.sel_remove = event.ctrl
        self.boxsel = True
        if whole:
            self.apply_box(set(self.box_cells))
        else:
            self.update_box(event)

    def apply_box(self, inside):
        want = (self.box_base - inside) if self.sel_remove else (self.box_base | inside)
        for c in list(self.selected - want):
            self.select_cell(c, False)
        for c in list(want - self.selected):
            self.select_cell(c, True)

    def update_box(self, event):
        a = self.box_axis
        m = self.mouse_pos(event)
        s = self.box_start
        plane_co = self.origin.copy()
        plane_co[a] = self.origin[a] + (self.box_layer + self.box_fs * 0.5) * self.grid_size
        o = [i for i in range(3) if i != a]
        lo = [10 ** 9, 10 ** 9]
        hi = [-10 ** 9, -10 ** 9]
        for x, y in ((s.x, s.y), (m.x, s.y), (m.x, m.y), (s.x, m.y)):
            c = Vector((x, y))
            ro = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, c)
            rv = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, c)
            p = geometry.intersect_line_plane(ro, ro + rv, plane_co, AXES[a])
            if p is None:
                self.apply_box(set())
                return
            for i, ax in enumerate(o):
                v = math.floor((p[ax] - self.origin[ax]) / self.grid_size + 0.5)
                lo[i] = min(lo[i], v)
                hi[i] = max(hi[i], v)
        inside = {c for c in self.box_cells
                  if all(lo[i] <= c[ax] <= hi[i] for i, ax in enumerate(o))}
        self.apply_box(inside)

    def delete_selected(self):
        self.cur = {"add": [], "erase": []}
        for c in list(self.selected):
            ob = self.cells.get(c)
            t = self.tmpl_of(ob)
            if t is not None and self.remove_block(c):
                self.cur["erase"].append((c, t))
        self.commit_cur()

    # ---------- размножение выбранного (Z) ----------
    def start_extrude(self, event, cut=False, move=False):
        if not self.selected:
            self.report({'INFO'}, "Сначала выбери блоки: Shift+ЛКМ")
            return
        self.mode = 'EXTRUDE'
        self.ex_cut = cut
        self.ex_move = move
        self.mv_off = (0, 0, 0)
        self.mv_victims = []
        self.ex_cells = list(self.selected)
        self.ex_set = set(self.ex_cells)
        self.ex_start = self.mouse_pos(event)
        # Запоминаем реальные центры и размеры блоков. Раньше сдвиг считался по
        # ключам клеток, а у Z ключ = 0.5 м, поэтому копии вставали не туда.
        self.ex_items = []
        for c in self.ex_cells:
            ob = self.cells.get(c)
            t = self.tmpl_of(ob)
            if ob is None or t is None:
                continue
            self.ex_items.append({
                "tmpl": t,
                "center": self.block_center(ob),
                "dims": self.block_dimensions_world(ob),
                "yaw": int(ob.get("bp_yaw", 0)),
                "flip": bool(ob.get("bp_flip", 0)),
            })
        if not self.ex_items:
            self.mode = None
            self.report({'INFO'}, "Нечего размножать")
            return
        center = sum((it["center"] for it in self.ex_items), Vector()) / len(self.ex_items)
        p0 = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, center)
        self.ex_u = []
        for a in range(3):
            pa = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, center + AXES[a] * self.grid_size)
            self.ex_u.append((pa - p0) if (p0 is not None and pa is not None) else Vector((0, 0)))
        self.ex_axis, self.ex_sign, self.ex_layers = None, 1, []
        self.ex_lock = None
        self.area.header_text_set(
            ("Перемещение" if move else "Выемка (удаление)" if cut else "Размножение") +
            ": води мышью | X / Y / Z - зафиксировать ось (ещё раз - снять) | "
            "ЛКМ или Enter - подтвердить | Esc - отмена")

    def update_extrude(self, event):
        # В modal() вызывается именно это имя. В старой версии метода не было,
        # поэтому Blender 5.2 падал с AttributeError при движении мыши.
        self.drag_axis(event)

    def drag_axis(self, event):
        d = self.mouse_pos(event) - self.ex_start
        axis, sign, m = None, 1, 0
        if d.length > 12:
            if self.ex_lock is not None:
                axis = self.ex_lock
            else:
                best = 0.0
                for a in range(3):
                    u = self.ex_u[a]
                    if u.length < 8:
                        continue
                    cos = abs(d.dot(u)) / (d.length * u.length)
                    if cos > best:
                        best, axis = cos, a
            if axis is not None:
                u = self.ex_u[axis]
                if u.length < 8:          # ось смотрит прямо в камеру: мышь вверх = плюс
                    u = Vector((0, 40))
                t = d.dot(u) / (u.length ** 2)
                sign = 1 if t >= 0 else -1
                m = min(abs(round(t)), 64)
                if self.ex_cut:
                    m = max(m, 1)   # выемка: выбранный слой удаляется сразу, дальше углубляешь
        self.set_extrude(axis, sign, m)

    def keys_overlapping(self, lo, hi):
        """Ключи всех блоков, чей реальный бокс физически пересекает объём lo..hi.
        Ищем по геометрии, а не по ключу ровно одной клетки: если в стопке лежат
        блоки разной высоты (плиты, полублоки), ключи слоёв не совпадают с шагом
        выбранного блока, и выемка вверх останавливалась на первом слое."""
        eps = 1e-3
        g = self.grid_size
        m = max(self.max_dim, g)
        x0 = int(math.floor((lo.x - m) / g)) - 1
        x1 = int(math.ceil((hi.x + m) / g)) + 1
        y0 = int(math.floor((lo.y - m) / g)) - 1
        y1 = int(math.ceil((hi.y + m) / g)) + 1
        z0 = int(math.floor((lo.z - m) / Z_KEY_STEP)) - 1
        z1 = int(math.ceil(hi.z / Z_KEY_STEP)) + 1
        out = []
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    key = (x, y, z)
                    ob = self.cells.get(key)
                    if ob is None:
                        continue
                    olo, ohi = self.aabb_for(key, ob)
                    if (lo.x < ohi[0] - eps and hi.x > olo[0] + eps and
                            lo.y < ohi[1] - eps and hi.y > olo[1] + eps and
                            lo.z < ohi[2] - eps and hi.z > olo[2] + eps):
                        out.append(key)
        return out

    def undo_layer(self, layer):
        if self.ex_cut:      # выемку откатываем - блоки возвращаются
            for nc, t in layer:
                if self.restore_block(nc, t) and nc in self.ex_set:
                    self.select_cell(nc, True)
        else:                # размножение откатываем - копии удаляются
            for nc, t in layer:
                self.remove_block(nc)

    def clear_layers(self):
        while self.ex_layers:
            self.undo_layer(self.ex_layers.pop())

    def set_extrude(self, axis, sign, m):
        if axis != self.ex_axis or sign != self.ex_sign:
            self.clear_layers()
            self.ex_axis, self.ex_sign = axis, sign
        if axis is None:
            return
        while len(self.ex_layers) < m:
            i = len(self.ex_layers)
            layer = []
            for it in self.ex_items:
                step = it["dims"][axis]
                if self.ex_cut:
                    # слой 0 - сам выбранный слой
                    ctr = Vector(it["center"])
                    ctr[axis] += sign * i * step
                    half = it["dims"] / 2.0
                    for key in self.keys_overlapping(ctr - half, ctr + half):
                        t = self.tmpl_of(self.cells.get(key))
                        if t is not None and self.remove_block(key):
                            layer.append((key, t))
                else:
                    # копии начинаются со следующего слоя, смещение = реальный размер блока
                    ctr = Vector(it["center"])
                    ctr[axis] += sign * (i + 1) * step
                    key = self.make_block(None, it["tmpl"], center=ctr, yaw=it["yaw"], flip=it["flip"])
                    if key:
                        layer.append((key, it["tmpl"]))
            self.ex_layers.append(layer)
        while len(self.ex_layers) > m:
            self.undo_layer(self.ex_layers.pop())

    def end_extrude(self, commit):
        if commit:
            ops = [x for layer in self.ex_layers for x in layer]
            if ops:
                if self.ex_cut:
                    self.history.append({"add": [], "erase": ops})
                else:
                    self.history.append({"add": ops, "erase": []})
                self.redo.clear()
                bpy.ops.ed.undo_push(message="Block Paint Extrude")
            self.ex_layers = []
        else:
            self.clear_layers()
        self.mode = None
        self.area.header_text_set(HINT)

    # ---------- заливка (F) ----------
    def fill_at(self, event):
        t = self.target_from_click(event)
        if not t:
            return
        start, axis, sign, support_ob, face_z = t
        if axis != 2:
            self.report({'WARNING'}, "Заливка работает на горизонтальных плоскостях: кликни по полу или по верху/низу блока")
            return
        self.cur_q = self.view_quarter()
        self.cur_flip = self.hit_flip
        bottom_z = face_z
        if sign < 0:
            bottom_z = face_z - self.template_dimensions_world(self.pick_template()).z
        # Занятость считаем ФИЗИЧЕСКИ: клетка занята, если в объёме нового блока
        # (от bottom_z на высоту блока) уже что-то стоит. Раньше брались только блоки
        # с тем же ключом слоя, и стенка из блоков, начинающихся ниже/выше (плиты,
        # полублоки, разная высота), не считалась контуром - отсюда ложное
        # "контур не замкнут".
        tmpl = self.pick_template()
        size = self.template_dimensions_world(tmpl)
        w, d = (size.y, size.x) if self.cur_q % 2 else (size.x, size.y)
        z_lo, z_hi = bottom_z, bottom_z + size.z
        g = self.grid_size
        eps = 1e-3
        blocked = set()
        for key, ob in self.cells.items():
            if ob is None:
                continue
            olo, ohi = self.aabb_for(key, ob)
            if not (olo[2] < z_hi - eps and ohi[2] > z_lo + eps):
                continue
            ix0 = int(math.floor((olo[0] - w / 2.0) / g)) - 1
            ix1 = int(math.ceil((ohi[0] + w / 2.0) / g)) + 1
            iy0 = int(math.floor((olo[1] - d / 2.0) / g)) - 1
            iy1 = int(math.ceil((ohi[1] + d / 2.0) / g)) + 1
            for ix in range(ix0, ix1 + 1):
                if not (ix * g - w / 2.0 < ohi[0] - eps and ix * g + w / 2.0 > olo[0] + eps):
                    continue
                for iy in range(iy0, iy1 + 1):
                    if iy * g - d / 2.0 < ohi[1] - eps and iy * g + d / 2.0 > olo[1] + eps:
                        blocked.add((ix, iy))
        if not blocked:
            self.report({'WARNING'}, "В этой плоскости нет контура")
            return
        sxy = (start[0], start[1])
        if sxy in blocked:
            self.report({'WARNING'}, "Клик попал в занятую клетку: кликни по полу внутри контура")
            return
        cells_xy, leak = _flood_cells(blocked, sxy)
        if cells_xy is None:
            self.report({'WARNING'}, "Контур не замкнут: заливка вытекает у клетки X=%.2f Y=%.2f (там дыра в стенке)"
                        % (leak[0] * g, leak[1] * g))
            return
        self.cur = {"add": [], "erase": []}
        for (x, y) in sorted(cells_xy):
            self.put((x, y, start[2]), None, None, 1, bottom_z)
        self.commit_cur()

    # ---------- события ----------
    def finish(self, context):
        if self.mode == 'EXTRUDE':
            self.end_extrude(False)
        self.clear_selection()
        if hasattr(self, "timer"):
            try:
                context.window_manager.event_timer_remove(self.timer)
            except Exception:
                pass
        self.area.header_text_set(None)
        return {'FINISHED'}

    def modal(self, context, event):
        is_release = event.type == 'LEFTMOUSE' and event.value == 'RELEASE'
        if is_release and self.mode is None and not (
                self.painting or self.erasing or self.selecting or self.boxsel):
            return {'PASS_THROUGH'}  # отпускание кнопки не наше - иначе оси не срабатывают
        if not is_release and not self.in_view(event):
            return {'PASS_THROUGH'}  # мышь над боковой панелью - можно крутить настройки
        if event.type in NAV_TYPES or event.type.startswith('NUMPAD'):
            return {'PASS_THROUGH'}
        self.mouse = self.mouse_pos(event)

        # --- режим размножения ---
        if self.mode == 'EXTRUDE':
            if event.type == 'MOUSEMOVE':
                self.update_extrude(event)
            elif event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'} and not event.is_repeat:
                a = 'XYZ'.index(event.type)
                self.ex_lock = None if self.ex_lock == a else a
                self.update_extrude(event)
            elif event.value == 'PRESS' and event.type in {'LEFTMOUSE', 'RET'}:
                self.end_extrude(True)
            elif event.value == 'PRESS' and event.type in {'ESC', 'RIGHTMOUSE'}:
                self.end_extrude(False)
            return {'RUNNING_MODAL'}

        busy = self.painting or self.erasing or self.selecting or self.boxsel

        if event.value == 'PRESS' and event.type in {'ESC', 'RIGHTMOUSE'}:
            return self.finish(context)

        if event.value == 'PRESS' and not busy:
            if event.type == 'Z':
                if event.ctrl:
                    (self.redo_step if event.shift else self.undo_step)()
                elif not event.is_repeat:
                    self.start_extrude(event)
                return {'RUNNING_MODAL'}
            if event.type == 'C' and not event.ctrl and not event.is_repeat:
                self.start_extrude(event, cut=True)
                return {'RUNNING_MODAL'}
            if event.type == 'F' and not event.is_repeat:
                self.fill_at(event)
                return {'RUNNING_MODAL'}
            if event.type == 'X' and not event.is_repeat:
                self.delete_selected()
                return {'RUNNING_MODAL'}
            if event.type == 'A' and not event.is_repeat:
                if event.alt:
                    self.clear_selection()
                else:
                    for c in list(self.cells):
                        self.select_cell(c, True)
                return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.cur = {"add": [], "erase": []}
                if event.alt:
                    self.begin_box(event, whole=event.shift)
                elif event.shift:
                    self.selecting = True
                    self.sel_remove = event.ctrl
                    hit = self.raycast_block(event)
                    if hit:
                        self.select_cell(self.key_of(hit[0]), not self.sel_remove)
                    elif not self.sel_remove:
                        self.clear_selection()
                elif event.ctrl:
                    self.erasing = True
                    self.erase_at(event)
                else:
                    self.begin_paint(event)
            elif event.value == 'RELEASE':
                self.commit_cur()
                self.painting = self.erasing = self.selecting = self.boxsel = False
                self.last = None
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            if self.painting:
                # Keep the whole stroke on the layer captured at mouse-down.
                target = self._paint_target_from_event(event)
                if target:
                    cell, axis, sign, support_ob, face_z = target
                    # Старт был на боковой грани: клетки на стороне опоры и за ней
                    # не принимаем, блок никогда не "проходит сквозь" опору.
                    if self.axis != 2 and (cell[self.axis] - self.paint_start_cell[self.axis]) * self.sign < 0:
                        return {'RUNNING_MODAL'}
                    if cell != self.last:
                        self.stroke(cell, None, None, 1, self.paint_bottom_z)
            elif self.erasing:
                self.erase_at(event)
            elif self.boxsel:
                self.update_box(event)
            elif self.selecting:
                hit = self.raycast_block(event)
                if hit:
                    self.select_cell(self.key_of(hit[0]), not self.sel_remove)
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}


# ======================= регистрация =======================

classes = (BP_Block, BP_UL_blocks, BP_OT_add_selected, BP_OT_remove, BP_PT_panel, BP_OT_run)
addon_keymaps = []


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.bp_blocks = bpy.props.CollectionProperty(type=BP_Block)
    bpy.types.Scene.bp_index = bpy.props.IntProperty()
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm else None
    if kc:
        km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new("bpaint.run", 'B', 'PRESS', ctrl=True, shift=True)
        addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()
    for name in ("bp_blocks", "bp_index"):
        try:
            delattr(bpy.types.Scene, name)
        except Exception:
            pass
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass


if __name__ == "__main__":
    unregister()
    register()
