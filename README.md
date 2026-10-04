# Block Painter (Early Beta / Raw Project)

**Block Painter** is a simple, experimental Blender plugin for building with blocks on a grid, similar to Minecraft mechanics. I made it for myself to stop copy-pasting every single wall and floor by hand.

⚠️ **Please note:** This is a very raw, early-stage project. I haven't tested it for thousands of hours, so **it definitely has bugs**. Depending on your Blender version or how your 3D models are built, it might behave differently or break. Use it at your own risk!

## What it can do right now:
* **Paint with your own models:** You can add any custom block or slab to the palette list using the eyedropper (pipette) tool and start building with it.
* **Auto-align for stairs:** Stairs and corner stairs try to rotate automatically based on where your camera looks, so you don't have to rotate them manually.
* **Basic tools:** It has simple features to place blocks, erase them, extrude lines, indent, and do a basic contour fill.

## How to install:
1. Download the `BlockPainter.py` file from this repository.
2. In Blender, go to `Edit` > `Preferences` > `Add-ons`.
3. Click `Install...` and select the downloaded `.py` file.
4. Enable the add-on. Open the `N` panel in the 3D Viewport to find **Block Paint**.

If you decide to try it, keep in mind that you might need to adjust your assets or settings individually to make it work correctly on your setup. 

Быстрый старт
Создай куб (Shift+A → Mesh → Cube) размером 1×1×1 м и проверь это в N → Item → Dimensions.
Открой панель N → вкладка Block Paint.
Выдели куб и нажми + справа от списка ассетов. Он попадёт в палитру.
Нажми «Рисовать» или Ctrl+Shift+B.
Рисуй левой кнопкой мыши. Выход: Esc 


Как это работает
Один мазок рисует один слой. Зажал ЛКМ и повёл мышь: блоки встают на одной высоте. Чтобы построить следующий слой, отпусти кнопку и нажми по верхней грани блока.
Стены. Нажми на боковую грань существующего блока, и блоки пойдут наружу от неё.
Поворот. Блоки сами поворачиваются лицом к тебе с шагом 90°.
Лестницы. Если в имени ассета есть слово stair (в любом регистре и в любом месте), он ведёт себя как лестница в Майнкрафте. Если ставить его снизу блока или на верхнюю половину боковой грани, он будет перевёрнут.
Угловые лестницы. Если в имени есть stair и ещё angle или corner (например stairs_corner), блок сам выбирает поворот и переворот по соседним лестницам. Если соседей нет, он ставится как обычная лестница.
Блоки сохраняются. После выхода по Esc блоки остаются в сцене, и при повторном запуске плагин снова с ними работает. 


Настройки в коде

В начале файла есть несколько значений, которые можно поменять:

Параметр	Что делает
GRID_SIZE = 1	Шаг сетки по X и Y, в метрах. Он должен совпадать с размером твоего ассета: куб 1×1×1 м требует шаг 1.
Z_KEY_STEP = 0.5	Шаг ключей по высоте. Нужен, чтобы плиты и блоки разной высоты были разными слоями. Обычно трогать не нужно.
STAIRS_TAG = "stair"	Слово в имени ассета, по которому блок считается лестницей.
STAIRS_AUTO_FLIP = True	Автоматический переворот лестниц. False: лестницы всегда ставятся как обычные блоки.
CORNER_WORDS = ("angle", "corner")	Слова в имени, по которым блок считается угловой лестницей.
CORNER_AUTO = True	Автоопределение поворота угловых лестниц. False: они ставятся как обычные лестницы.

Горячую клавишу запуска можно поменять в функции register(): строка с 'B', 'PRESS', ctrl=True, shift=True.

Если блоки ставятся с щелями или неровно

Почти всегда причина в размере ассета, а не в настройках проекта.

Проверь N → Item → Dimensions: там должно быть значение, равное GRID_SIZE по всем осям.
Если масштаб не равен 1, примени его: Ctrl+A → Scale.
Стандартный куб Blender имеет размер 2×2×2 м. Новый куб из Shift+A → Mesh → Cube имеет размер 1×1×1 (если поменять размер при создании, он тоже изменится).
Проверь, что у ассета нет родителя и нет Delta Scale, а поворот кратен 90°.
Если блоки нужны другого размера, например 0.5 м, поставь GRID_SIZE = 0.5.

