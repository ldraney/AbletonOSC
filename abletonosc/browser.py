"""Browser operations for AbletonOSC.

Provides access to Ableton's browser for exploring packs and loading devices.
Enables recursive searching through pack contents to find nested presets.
"""

from typing import Tuple, Any, List
import Live
from .handler import AbletonOSCHandler


class BrowserHandler(AbletonOSCHandler):
    def __init__(self, manager):
        super().__init__(manager)
        self.class_identifier = "browser"

    def init_api(self):
        application = Live.Application.get_application()
        browser = application.browser

        # =============================================================================
        # List Packs
        # =============================================================================

        def browser_list_packs(_):
            """List all installed pack names.

            Returns tuple of pack names.
            """
            try:
                pack_names = []
                for pack in browser.packs.iter_children:
                    pack_names.append(pack.name)
                self.logger.info("Found %d packs" % len(pack_names))
                return tuple(pack_names)
            except Exception as e:
                self.logger.error("Error listing packs: %s" % str(e))
                return ()

        self.osc_server.add_handler("/live/browser/list_packs", browser_list_packs)

        # =============================================================================
        # List Pack Contents (Recursive)
        # =============================================================================

        def browser_list_pack_contents(params: Tuple[Any]):
            """List all loadable items in a pack.

            Args:
                params[0]: Pack name to search
                params[1]: (optional) Max depth for recursion, default 10

            Returns tuple of loadable item names with their full paths.
            """
            if len(params) < 1:
                self.logger.warning("list_pack_contents requires pack name")
                return ()

            pack_name = str(params[0])
            max_depth = int(params[1]) if len(params) > 1 else 10

            # Find the pack
            target_pack = None
            for pack in browser.packs.iter_children:
                if pack.name == pack_name or pack_name.lower() in pack.name.lower():
                    target_pack = pack
                    break

            if not target_pack:
                self.logger.warning("Pack not found: %s" % pack_name)
                return ()

            results = []
            self._collect_loadable_items(target_pack, "", results, max_depth)
            self.logger.info("Found %d loadable items in pack '%s'" % (len(results), pack_name))
            return tuple(results)

        def _collect_loadable_items(item, path, results, depth):
            """Recursively collect loadable items from a browser item."""
            if depth <= 0:
                return

            current_path = path + "/" + item.name if path else item.name

            try:
                for child in item.iter_children:
                    if child.is_loadable:
                        results.append(current_path + "/" + child.name)
                    if child.is_folder:
                        _collect_loadable_items(child, current_path, results, depth - 1)
            except Exception as e:
                self.logger.debug("Error iterating children of %s: %s" % (current_path, str(e)))

        self._collect_loadable_items = _collect_loadable_items
        self.osc_server.add_handler("/live/browser/list_pack_contents", browser_list_pack_contents)

        # =============================================================================
        # Search Browser (All Packs)
        # =============================================================================

        def browser_search(params: Tuple[Any]):
            """Search all packs for items matching a query.

            Args:
                params[0]: Search query string
                params[1]: (optional) Max results, default 50
                params[2]: (optional) Max depth for recursion, default 10

            Returns tuple of (name, pack_name) pairs for matching items.
            """
            if len(params) < 1:
                self.logger.warning("search requires query string")
                return ()

            query = str(params[0]).lower()
            max_results = int(params[1]) if len(params) > 1 else 50
            max_depth = int(params[2]) if len(params) > 2 else 10

            results = []

            # Search through all packs
            for pack in browser.packs.iter_children:
                if len(results) >= max_results:
                    break
                self._search_item(pack, query, results, max_results, max_depth, pack.name)

            # Flatten results to tuple of strings: "item_name|pack_name|path"
            output = []
            for item_name, pack_name, path in results:
                output.append("%s|%s|%s" % (item_name, pack_name, path))

            self.logger.info("Found %d items matching '%s'" % (len(output), query))
            return tuple(output)

        def _search_item(item, query, results, max_results, depth, pack_name, path=""):
            """Recursively search browser items for matching names."""
            if depth <= 0 or len(results) >= max_results:
                return

            current_path = path + "/" + item.name if path else item.name

            try:
                for child in item.iter_children:
                    if len(results) >= max_results:
                        break

                    if child.is_loadable and query in child.name.lower():
                        results.append((child.name, pack_name, current_path + "/" + child.name))

                    if child.is_folder:
                        _search_item(child, query, results, max_results, depth - 1, pack_name, current_path)
            except Exception as e:
                self.logger.debug("Error searching %s: %s" % (current_path, str(e)))

        self._search_item = _search_item
        self.osc_server.add_handler("/live/browser/search", browser_search)

        # =============================================================================
        # Load Item by Path
        # =============================================================================

        def browser_load_item(params: Tuple[Any]):
            """Load a browser item by its full path.

            The path should be in format: "Pack Name/Folder/Subfolder/Item Name"

            Args:
                params[0]: Full path to the item

            Returns (1,) on success, (-1,) on failure.
            """
            if len(params) < 1:
                self.logger.warning("load_item requires item path")
                return (-1,)

            full_path = str(params[0])
            path_parts = full_path.split("/")

            if len(path_parts) < 2:
                self.logger.warning("Invalid path format: %s" % full_path)
                return (-1,)

            pack_name = path_parts[0]
            item_path = path_parts[1:]

            # Find the pack
            target_pack = None
            for pack in browser.packs.iter_children:
                if pack.name == pack_name or pack_name.lower() in pack.name.lower():
                    target_pack = pack
                    break

            if not target_pack:
                self.logger.warning("Pack not found: %s" % pack_name)
                return (-1,)

            # Navigate to the item
            current_item = target_pack
            for i, part in enumerate(item_path):
                found = False
                try:
                    for child in current_item.iter_children:
                        if child.name == part or part.lower() in child.name.lower():
                            current_item = child
                            found = True
                            break
                except Exception as e:
                    self.logger.warning("Error navigating path: %s" % str(e))
                    return (-1,)

                if not found:
                    self.logger.warning("Path component not found: %s (in %s)" % (part, full_path))
                    return (-1,)

            # Load the item
            if current_item.is_loadable:
                browser.load_item(current_item)
                self.logger.info("Loaded item: %s" % full_path)
                return (1,)
            else:
                self.logger.warning("Item is not loadable: %s" % full_path)
                return (-1,)

        self.osc_server.add_handler("/live/browser/load_item", browser_load_item)

        # =============================================================================
        # Search and Load (Convenience)
        # =============================================================================

        def browser_search_and_load(params: Tuple[Any]):
            """Search for an item and load the first match.

            Searches all packs recursively for an item matching the query
            and loads the first match found.

            Args:
                params[0]: Search query string

            Returns (item_name,) on success, ("",) on failure.
            """
            if len(params) < 1:
                self.logger.warning("search_and_load requires query string")
                return ("",)

            query = str(params[0]).lower()

            # Search through all packs
            for pack in browser.packs.iter_children:
                result = self._find_and_load(pack, query, 10)
                if result:
                    return (result,)

            # Also search standard locations
            search_locations = [
                browser.instruments,
                browser.audio_effects,
                browser.midi_effects,
                browser.drums,
                browser.sounds,
            ]

            for location in search_locations:
                result = self._find_and_load(location, query, 10)
                if result:
                    return (result,)

            self.logger.warning("No item found matching: %s" % query)
            return ("",)

        def _find_and_load(item, query, depth):
            """Recursively find and load first matching item."""
            if depth <= 0:
                return None

            try:
                for child in item.iter_children:
                    # Check if this item matches
                    if child.is_loadable and query in child.name.lower():
                        browser.load_item(child)
                        self.logger.info("Found and loaded: %s" % child.name)
                        return child.name

                    # Recurse into folders
                    if child.is_folder:
                        result = _find_and_load(child, query, depth - 1)
                        if result:
                            return result
            except Exception as e:
                self.logger.debug("Error searching: %s" % str(e))

            return None

        self._find_and_load = _find_and_load
        self.osc_server.add_handler("/live/browser/search_and_load", browser_search_and_load)

        # =============================================================================
        # Get Standard Browser Locations
        # =============================================================================

        def browser_list_instruments(_):
            """List top-level items in the instruments browser."""
            try:
                items = []
                for item in browser.instruments.iter_children:
                    items.append(item.name)
                return tuple(items)
            except Exception as e:
                self.logger.error("Error listing instruments: %s" % str(e))
                return ()

        def browser_list_audio_effects(_):
            """List top-level items in the audio effects browser."""
            try:
                items = []
                for item in browser.audio_effects.iter_children:
                    items.append(item.name)
                return tuple(items)
            except Exception as e:
                self.logger.error("Error listing audio effects: %s" % str(e))
                return ()

        def browser_list_midi_effects(_):
            """List top-level items in the MIDI effects browser."""
            try:
                items = []
                for item in browser.midi_effects.iter_children:
                    items.append(item.name)
                return tuple(items)
            except Exception as e:
                self.logger.error("Error listing MIDI effects: %s" % str(e))
                return ()

        def browser_list_drums(_):
            """List top-level items in the drums browser."""
            try:
                items = []
                for item in browser.drums.iter_children:
                    items.append(item.name)
                return tuple(items)
            except Exception as e:
                self.logger.error("Error listing drums: %s" % str(e))
                return ()

        def browser_list_sounds(_):
            """List top-level items in the sounds browser."""
            try:
                items = []
                for item in browser.sounds.iter_children:
                    items.append(item.name)
                return tuple(items)
            except Exception as e:
                self.logger.error("Error listing sounds: %s" % str(e))
                return ()

        self.osc_server.add_handler("/live/browser/list_instruments", browser_list_instruments)
        self.osc_server.add_handler("/live/browser/list_audio_effects", browser_list_audio_effects)
        self.osc_server.add_handler("/live/browser/list_midi_effects", browser_list_midi_effects)
        self.osc_server.add_handler("/live/browser/list_drums", browser_list_drums)
        self.osc_server.add_handler("/live/browser/list_sounds", browser_list_sounds)
