
Demo video: https://www.reddit.com/r/blender/s/SyfM8JcdSh


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

Quick Start
Create a cube (Shift+A → Mesh → Cube). In the operator panel at the bottom left, set Size to 1 m, then check N → Item → Dimensions: it should read 1 × 1 × 1 m.
Open the N panel → Block Paint tab.
Select the cube and click + next to the asset list. It will be added to the palette.
Click "Paint" or press Ctrl+Shift+B.
Paint with the left mouse button. Exit: Esc.
How It Works
One stroke paints one layer. Hold LMB and move the mouse: blocks are placed at the same height. To build the next layer, release the button and click on the top face of a block.
Walls. Click on the side face of an existing block, and new blocks grow outward from it.
Rotation. Blocks automatically rotate to face you in 90° steps.
Stairs. If the asset's name contains the word stair (any case, anywhere in the name), it behaves like a Minecraft staircase. If you place it on the underside of a block or on the upper half of a side face, it will be flipped upside down.
Corner stairs. If the name contains stair plus angle or corner (for example stairs_corner), the block picks its rotation and flip automatically based on neighboring stairs. If there are no neighbors, it is placed as a regular staircase.
Blocks are persistent. After you exit with Esc, the blocks stay in the scene, and the add-on picks them up again the next time you run it.
Settings in the Code

There are a few values at the top of the file that you can change:

Parameter	What it does
GRID_SIZE = 1	Grid step on X and Y, in meters. It must match the size of your asset: a 1×1×1 m cube needs a step of 1.
Z_KEY_STEP = 0.5	Height key step. It lets slabs and blocks of different heights occupy separate layers. Usually there's no need to change it.
STAIRS_TAG = "stair"	The word in an asset's name that makes it count as a staircase.
STAIRS_AUTO_FLIP = True	Automatic stair flipping. False: stairs are always placed like regular blocks.
CORNER_WORDS = ("angle", "corner")	Words in the name that mark a block as a corner staircase.
CORNER_AUTO = True	Automatic rotation of corner stairs. False: they are placed like regular stairs.

You can change the launch hotkey in the register() function: look for the line with 'B', 'PRESS', ctrl=True, shift=True.

If Blocks Are Placed With Gaps or Unevenly

Almost always the cause is the asset's size, not the project settings.

Check N → Item → Dimensions: the values should equal GRID_SIZE on all axes.
If the scale is not 1, apply it: Ctrl+A → Scale.
Blender's default cube is 2×2×2 m, and a cube added with Shift+A → Mesh → Cube is also 2 m by default. Set its Size to 1 m in the Adjust Last Operation panel, or set GRID_SIZE = 2 to match.
Make sure the asset has no parent and no Delta Scale, and that its rotation is a multiple of 90°.
If you want blocks of a different size, for example 0.5 m, set GRID_SIZE = 0.5.
