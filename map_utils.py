"""
Utility functions and classes for the CRESST/GAIA landing page map.
"""

import requests
import xml.etree.ElementTree as ET
import numpy as np
import matplotlib
import matplotlib.colors as mcolors
import branca.colormap as bcm
from folium.elements import MacroElement
from jinja2 import Template


def mpl_to_branca(cmap, vmin=0, vmax=1, n=256):
    """
    Convert a matplotlib colormap to a branca LinearColormap.

    Parameters
    ----------
    cmap : matplotlib colormap or str
        Colormap instance or name (e.g. 'viridis')
    vmin, vmax : float
        Data range for the branca colormap
    n : int
        Number of color samples

    Returns
    -------
    branca.colormap.LinearColormap
    """
    if isinstance(cmap, str):
        cmap = matplotlib.colormaps.get_cmap(cmap)

    colors = [
        mcolors.to_hex(cmap(i))
        for i in np.linspace(0, 1, n)
    ]

    return bcm.LinearColormap(
        colors=colors,
        vmin=vmin,
        vmax=vmax
    )


def get_gibs_legend_url(layer_name, wms_url="https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi"):
    """
    Fetch the legend URL for a given NASA GIBS layer from WMS GetCapabilities.

    Parameters
    ----------
    layer_name : str
        The GIBS layer identifier (e.g., 'OPERA_L3_DIST-ANN-HLS_Color_Index')
    wms_url : str
        The WMS endpoint URL

    Returns
    -------
    str or None
        The legend URL if found, otherwise None
    """
    capabilities_url = f"{wms_url}?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0"

    response = requests.get(capabilities_url)
    response.raise_for_status()

    # Parse XML
    root = ET.fromstring(response.content)

    # Define namespace (WMS 1.3.0 uses this namespace)
    ns = {'wms': 'http://www.opengis.net/wms'}

    # Find the layer by name
    for layer in root.findall('.//wms:Layer', ns):
        name_elem = layer.find('wms:Name', ns)
        if name_elem is not None and name_elem.text == layer_name:
            # Look for LegendURL
            legend_url_elem = layer.find('.//wms:LegendURL/wms:OnlineResource', ns)
            if legend_url_elem is not None:
                # Get the href attribute (uses xlink namespace)
                href = legend_url_elem.get('{http://www.w3.org/1999/xlink}href')
                return href

    return None


class ToggleableLayerColorbar(MacroElement):
    """
    A colorbar legend that toggles visibility based on layer add/remove events.
    Works with TreeLayerControl by tracking the layer object directly.
    """
    _counter = 0  # Class-level counter for unique IDs

    def __init__(self, layer, colormap):
        """
        Parameters
        ----------
        layer : folium layer object
            The layer to associate with this colorbar (e.g., a TileLayer)
        colormap : branca colormap
            The colormap to display
        """
        super().__init__()
        self.layer = layer
        self.colormap = colormap
        ToggleableLayerColorbar._counter += 1
        self.legend_var_name = f"layer_legend_{ToggleableLayerColorbar._counter}"

        self._template = Template("""
        {% macro script(this, kwargs) %}
        // Initialize registry if not exists
        if (typeof window._layerColorbarLegends === 'undefined') {
            window._layerColorbarLegends = {};
        }

        var {{ this.legend_var_name }} = L.control({position: 'bottomright'});
        {{ this.legend_var_name }}.onAdd = function (map) {
            var div = L.DomUtil.create('div', 'info legend');
            div.style.backgroundColor = 'white';
            div.style.padding = '10px';
            div.innerHTML = `{{ this.colormap._repr_html_() }}`;
            return div;
        };
        // Don't add to map initially - will be added when layer is shown
        {{ this.legend_var_name }}._isOnMap = false;

        // Get reference to the layer
        var targetLayer_{{ this.legend_var_name }} = {{ this.layer.get_name() }};

        // Register this legend with the layer reference
        window._layerColorbarLegends['{{ this.legend_var_name }}'] = {
            legend: {{ this.legend_var_name }},
            layer: targetLayer_{{ this.legend_var_name }}
        };

        // Listen for layer add events on the map
        {{ this._parent.get_name() }}.on('layeradd', function(e) {
            if (e.layer === targetLayer_{{ this.legend_var_name }}) {
                // Remove all other legends from the map first
                for (var key in window._layerColorbarLegends) {
                    var entry = window._layerColorbarLegends[key];
                    if (entry.legend._isOnMap) {
                        entry.legend.remove();
                        entry.legend._isOnMap = false;
                    }
                }
                // Add this legend to the map
                {{ this.legend_var_name }}.addTo({{ this._parent.get_name() }});
                {{ this.legend_var_name }}._isOnMap = true;
            }
        });

        // Listen for layer remove events on the map
        {{ this._parent.get_name() }}.on('layerremove', function(e) {
            if (e.layer === targetLayer_{{ this.legend_var_name }}) {
                if ({{ this.legend_var_name }}._isOnMap) {
                    {{ this.legend_var_name }}.remove();
                    {{ this.legend_var_name }}._isOnMap = false;
                }
            }
        });
        {% endmacro %}
        """)


class ToggleableEsriLegend(MacroElement):
    """
    A legend that toggles visibility based on layer add/remove events.
    Builds HTML legend from ESRI MapServer legend JSON response.
    """
    _counter = 0

    def __init__(self, layer, legend_json, title="Legend"):
        """
        Parameters
        ----------
        layer : folium layer object
            The layer to associate with this legend
        legend_json : dict
            The JSON response from ESRI MapServer legend endpoint
        title : str
            Title to display at the top of the legend
        """
        super().__init__()
        self.layer = layer
        self.legend_json = legend_json
        self.title = title
        ToggleableEsriLegend._counter += 1
        self.legend_var_name = f"esri_legend_{ToggleableEsriLegend._counter}"

        # Build the legend HTML from the JSON
        self.legend_html = self._build_legend_html()

        self._template = Template("""
        {% macro script(this, kwargs) %}
        // Initialize registry if not exists
        if (typeof window._layerEsriLegends === 'undefined') {
            window._layerEsriLegends = {};
        }

        var {{ this.legend_var_name }} = L.control({position: 'bottomright'});
        {{ this.legend_var_name }}.onAdd = function (map) {
            var div = L.DomUtil.create('div', 'info legend');
            div.style.backgroundColor = 'white';
            div.style.padding = '10px';
            div.style.maxHeight = '300px';
            div.style.overflowY = 'auto';
            div.innerHTML = `{{ this.legend_html }}`;
            return div;
        };
        {{ this.legend_var_name }}._isOnMap = false;

        var targetLayer_{{ this.legend_var_name }} = {{ this.layer.get_name() }};

        window._layerEsriLegends['{{ this.legend_var_name }}'] = {
            legend: {{ this.legend_var_name }},
            layer: targetLayer_{{ this.legend_var_name }}
        };

        {{ this._parent.get_name() }}.on('layeradd', function(e) {
            if (e.layer === targetLayer_{{ this.legend_var_name }}) {
                // Remove all colorbar legends first
                if (typeof window._layerColorbarLegends !== 'undefined') {
                    for (var key in window._layerColorbarLegends) {
                        var entry = window._layerColorbarLegends[key];
                        if (entry.legend._isOnMap) {
                            entry.legend.remove();
                            entry.legend._isOnMap = false;
                        }
                    }
                }
                // Remove all ESRI legends
                for (var key in window._layerEsriLegends) {
                    var entry = window._layerEsriLegends[key];
                    if (entry.legend._isOnMap) {
                        entry.legend.remove();
                        entry.legend._isOnMap = false;
                    }
                }
                {{ this.legend_var_name }}.addTo({{ this._parent.get_name() }});
                {{ this.legend_var_name }}._isOnMap = true;
            }
        });

        {{ this._parent.get_name() }}.on('layerremove', function(e) {
            if (e.layer === targetLayer_{{ this.legend_var_name }}) {
                if ({{ this.legend_var_name }}._isOnMap) {
                    {{ this.legend_var_name }}.remove();
                    {{ this.legend_var_name }}._isOnMap = false;
                }
            }
        });
        {% endmacro %}
        """)

    def _build_legend_html(self):
        """Build HTML string from ESRI legend JSON."""
        html = f'<b>{self.title}</b><br>'

        if 'layers' in self.legend_json and len(self.legend_json['layers']) > 0:
            legend_items = self.legend_json['layers'][0].get('legend', [])
            for item in legend_items:
                label = item.get('label', '')
                image_data = item.get('imageData', '')
                content_type = item.get('contentType', 'image/png')

                html += f'''
                <div style="display: flex; align-items: center; margin: 2px 0;">
                    <img src="data:{content_type};base64,{image_data}"
                         style="width: 20px; height: 20px; margin-right: 5px;"/>
                    <span style="font-size: 12px;">{label}</span>
                </div>'''

        return html


class ToggleableGIBSLegend(MacroElement):
    """
    A legend that toggles visibility based on layer add/remove events.
    Displays a NASA GIBS legend image from their legend URL.
    """
    _counter = 0

    def __init__(self, layer, legend_url, title="Legend"):
        """
        Parameters
        ----------
        layer : folium layer object
            The layer to associate with this legend
        legend_url : str
            The URL to the GIBS legend image (SVG or PNG)
        title : str
            Title to display at the top of the legend
        """
        super().__init__()
        self.layer = layer
        # Convert PNG URL to SVG if needed
        self.legend_url = legend_url.replace('.png', '.svg') if legend_url else legend_url
        self.title = title
        ToggleableGIBSLegend._counter += 1
        self.legend_var_name = f"gibs_legend_{ToggleableGIBSLegend._counter}"

        self._template = Template("""
        {% macro script(this, kwargs) %}
        // Initialize registry if not exists
        if (typeof window._layerGIBSLegends === 'undefined') {
            window._layerGIBSLegends = {};
        }

        var {{ this.legend_var_name }} = L.control({position: 'bottomright'});
        {{ this.legend_var_name }}.onAdd = function (map) {
            var div = L.DomUtil.create('div', 'info legend');
            div.style.backgroundColor = 'white';
            div.style.padding = '6px';
            div.style.maxWidth = '200px';
            div.innerHTML = `<b style="font-size:11px;">{{ this.title }}</b><br><img src="{{ this.legend_url }}" style="max-width:100%;height:auto;"/>`;
            return div;
        };
        {{ this.legend_var_name }}._isOnMap = false;

        var targetLayer_{{ this.legend_var_name }} = {{ this.layer.get_name() }};

        window._layerGIBSLegends['{{ this.legend_var_name }}'] = {
            legend: {{ this.legend_var_name }},
            layer: targetLayer_{{ this.legend_var_name }}
        };

        {{ this._parent.get_name() }}.on('layeradd', function(e) {
            if (e.layer === targetLayer_{{ this.legend_var_name }}) {
                // Remove all colorbar legends first
                if (typeof window._layerColorbarLegends !== 'undefined') {
                    for (var key in window._layerColorbarLegends) {
                        var entry = window._layerColorbarLegends[key];
                        if (entry.legend._isOnMap) {
                            entry.legend.remove();
                            entry.legend._isOnMap = false;
                        }
                    }
                }
                // Remove all ESRI legends
                if (typeof window._layerEsriLegends !== 'undefined') {
                    for (var key in window._layerEsriLegends) {
                        var entry = window._layerEsriLegends[key];
                        if (entry.legend._isOnMap) {
                            entry.legend.remove();
                            entry.legend._isOnMap = false;
                        }
                    }
                }
                // Remove all GIBS legends
                for (var key in window._layerGIBSLegends) {
                    var entry = window._layerGIBSLegends[key];
                    if (entry.legend._isOnMap) {
                        entry.legend.remove();
                        entry.legend._isOnMap = false;
                    }
                }
                {{ this.legend_var_name }}.addTo({{ this._parent.get_name() }});
                {{ this.legend_var_name }}._isOnMap = true;
            }
        });

        {{ this._parent.get_name() }}.on('layerremove', function(e) {
            if (e.layer === targetLayer_{{ this.legend_var_name }}) {
                if ({{ this.legend_var_name }}._isOnMap) {
                    {{ this.legend_var_name }}.remove();
                    {{ this.legend_var_name }}._isOnMap = false;
                }
            }
        });
        {% endmacro %}
        """)
