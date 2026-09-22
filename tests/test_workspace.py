from pdf_workbench.core.models import (
    CustomSplitDirection,
    FourSplitOrder,
    SplitMode,
    custom_leaf_paths,
)
from pdf_workbench.core.workspace import custom_node_from_dict, settings_from_manifest


def test_custom_node_from_manifest_dict_round_trips_tree() -> None:
    node = custom_node_from_dict(
        {
            "type": "split",
            "direction": "vertical",
            "ratio": 0.42,
            "first": {
                "type": "split",
                "direction": "horizontal",
                "ratio": 0.6,
                "first": {"type": "leaf"},
                "second": {"type": "leaf"},
            },
            "second": {"type": "leaf"},
        }
    )

    assert node.direction is CustomSplitDirection.VERTICAL
    assert node.first is not None
    assert node.first.direction is CustomSplitDirection.HORIZONTAL
    assert custom_leaf_paths(node) == [(0, 0), (0, 1), (1,)]


def test_settings_from_manifest_restores_custom_order_and_regular_pages() -> None:
    manifest = {
        "source_pages": [
            {
                "source_page": 1,
                "split_mode": "custom",
                "x_ratio": 0.5,
                "y_ratio": 0.5,
                "overlap_px": 7,
                "four_split_order": "rtl_tb",
                "custom_layout": {
                    "type": "split",
                    "direction": "vertical",
                    "ratio": 0.4,
                    "first": {"type": "leaf"},
                    "second": {"type": "leaf"},
                },
                "custom_order": [[1], [0]],
            },
            {
                "source_page": 2,
                "split_mode": "four",
                "x_ratio": 0.45,
                "y_ratio": 0.55,
                "overlap_px": 3,
                "four_split_order": "ltr_tb",
            },
        ]
    }

    settings = settings_from_manifest(manifest)

    assert len(settings) == 2
    assert settings[0].mode is SplitMode.CUSTOM
    assert settings[0].overlap_px == 7
    assert settings[0].custom_order == [(1,), (0,)]
    assert settings[1].mode is SplitMode.CUSTOM
    assert settings[1].x_ratio == 0.45
    assert settings[1].y_ratio == 0.55
    assert settings[1].order is FourSplitOrder.LTR_TB
    assert settings[1].custom_order == [(1, 0), (1, 1), (0, 0), (0, 1)]
    assert settings[1].custom_root.ratio == 0.45
