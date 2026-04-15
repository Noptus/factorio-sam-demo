"""
Few-shot examples: MINING
=========================
These are verified working FLE Python code snippets that agents receive
before attempting any mining task.  The pattern is:

    get_resource_patches()  →  move_to()  →  harvest_resource()

All three examples follow the same structure but target different resources.
"""

# ─── Example 1: Mine Iron Ore ─────────────────────────────────────────────────
MINE_IRON_ORE = """
# Goal: gather 100 iron ore and confirm it is in the player inventory.

# 1. Find iron-ore patches within 100 tiles of the player
iron_patches = get_resource_patches('iron-ore', radius=100)
if not iron_patches:
    print("ERROR: No iron-ore patches found within 100 tiles.")
else:
    # 2. Sort by distance and pick the nearest patch
    nearest = min(iron_patches, key=lambda p: p.position.distance(get_position()))

    # 3. Walk to the patch
    move_to(nearest.position)

    # 4. Harvest the desired amount (FLE will stop if the patch is exhausted)
    harvest_resource(nearest.position, quantity=100)

    # 5. Verify
    inv = inspect_inventory()
    collected = inv.get('iron-ore', 0)
    print(f"Harvested {collected} iron-ore.  Patch has ~{nearest.amount} remaining.")
"""

# ─── Example 2: Mine Coal ─────────────────────────────────────────────────────
MINE_COAL = """
# Goal: gather 80 coal (needed as fuel for furnaces and burner drills).

coal_patches = get_resource_patches('coal', radius=100)
if not coal_patches:
    print("ERROR: No coal found within 100 tiles.")
else:
    nearest_coal = min(coal_patches, key=lambda p: p.position.distance(get_position()))
    move_to(nearest_coal.position)
    harvest_resource(nearest_coal.position, quantity=80)

    inv = inspect_inventory()
    print(f"Coal in inventory: {inv.get('coal', 0)}")
"""

# ─── Example 3: Mine Stone ────────────────────────────────────────────────────
MINE_STONE = """
# Goal: gather 50 stone (needed to craft stone furnaces).
# Pattern identical to iron-ore and coal.

stone_patches = get_resource_patches('stone', radius=100)
if not stone_patches:
    print("ERROR: No stone found within 100 tiles.")
else:
    nearest_stone = min(stone_patches, key=lambda p: p.position.distance(get_position()))
    move_to(nearest_stone.position)
    harvest_resource(nearest_stone.position, quantity=50)

    inv = inspect_inventory()
    print(f"Stone in inventory: {inv.get('stone', 0)}")
    # You now have enough stone to craft 8 stone furnaces (5 stone each, but
    # the recipe actually needs 5; crafting costs vary by Factorio version).
"""

# ─── Example 4: Mine Copper Ore (bonus) ──────────────────────────────────────
MINE_COPPER_ORE = """
# Goal: gather 80 copper ore (for copper plates / cables / circuits).

copper_patches = get_resource_patches('copper-ore', radius=100)
if not copper_patches:
    print("ERROR: No copper-ore patches found within 100 tiles.")
else:
    nearest_copper = min(copper_patches, key=lambda p: p.position.distance(get_position()))
    move_to(nearest_copper.position)
    harvest_resource(nearest_copper.position, quantity=80)

    inv = inspect_inventory()
    print(f"Copper-ore in inventory: {inv.get('copper-ore', 0)}")
"""

ALL_EXAMPLES = {
    "mine_iron_ore": MINE_IRON_ORE,
    "mine_coal": MINE_COAL,
    "mine_stone": MINE_STONE,
    "mine_copper_ore": MINE_COPPER_ORE,
}
