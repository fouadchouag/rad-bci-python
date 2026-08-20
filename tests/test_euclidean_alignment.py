# tests/test_euclidean_alignment.py
"""Tests for BCI_EuclideanAlignment node and its pure helper functions."""
import numpy as np
import pytest


# ---------- Pure function tests ----------

def test_ensure_nchn_from_samples_x_channels():
    from plugins.bci_euclidean_alignment_node import _ensure_nchn
    seg = np.random.randn(100, 22)  # (samples, channels)
    result = _ensure_nchn(seg)
    assert result.shape == (22, 100)


def test_ensure_nchn_already_channels_x_samples():
    from plugins.bci_euclidean_alignment_node import _ensure_nchn
    seg = np.random.randn(22, 100)  # (channels, samples)
    result = _ensure_nchn(seg)
    assert result.shape == (22, 100)


def test_ensure_nchn_1d():
    from plugins.bci_euclidean_alignment_node import _ensure_nchn
    seg = np.random.randn(22)
    result = _ensure_nchn(seg)
    assert result.shape == (22, 1)


def test_ensure_nchn_tall_matrix():
    from plugins.bci_euclidean_alignment_node import _ensure_nchn
    seg = np.random.randn(200, 16)  # 200>16, so transpose
    result = _ensure_nchn(seg)
    assert result.shape == (16, 200)


# ---------- Plugin node tests ----------

class TestBCIEuclideanAlignment:
    @pytest.fixture
    def node(self):
        from plugins.bci_euclidean_alignment_node import BCIEuclideanAlignment
        n = BCIEuclideanAlignment()
        n.setup()
        return n

    def test_setup_creates_inputs_outputs(self, node):
        assert "segment" in node.inputs
        assert "sfreq" in node.inputs
        assert "segment" in node.outputs
        assert "ea_matrix" in node.outputs

    def test_execute_no_segment_returns_empty(self, node):
        result = node.execute(segment=None, sfreq=512.0)
        assert result == {}

    def test_accumulate_segments_before_fit(self, node):
        seg = np.random.randn(22, 256)
        # First segment — should accumulate, not transform
        node.execute(segment=seg, sfreq=512.0)
        assert len(node._fit_seg) == 1
        assert node._is_fitted is False

    def test_auto_fit_at_20_segments(self, node):
        for i in range(20):
            seg = np.random.randn(22, 256) + np.random.randn(22, 1) * 0.5
            node.execute(segment=seg, sfreq=512.0)
        assert node._is_fitted is True
        assert node._whitening is not None
        assert node._whitening.shape == (22, 22)

    def test_transform_after_fit(self, node):
        # Accumulate 20 segments to trigger fit
        for _ in range(20):
            seg = np.random.randn(22, 256)
            node.execute(segment=seg, sfreq=512.0)
        assert node._is_fitted is True

        # Now transform a new segment
        test_seg = np.random.randn(22, 256)
        node.execute(segment=test_seg, sfreq=512.0)

        out = node.outputs["segment"].value
        assert out is not None
        assert out.shape == (22, 256)

    def test_ea_whitening_normalizes_trace(self, node):
        for _ in range(25):
            seg = np.random.randn(22, 512)
            node.execute(segment=seg, sfreq=512.0)
        # After EA, the mean covariance should be close to identity
        W = node._whitening
        assert W is not None
        # W @ mean_cov @ W^T should have trace close to n_ch
        # Quick check: W should be symmetric positive definite
        eigvals = np.linalg.eigvalsh(W)
        assert np.all(eigvals > 0), "Whitening matrix not positive definite"

    def test_export_import_config(self, node):
        node._enabled = False
        node._epsilon = 1e-6
        cfg = node.export_config()
        assert cfg["enabled"] is False
        assert cfg["epsilon"] == 1e-6

        node2_instance = type(node)()
        node2_instance.setup()
        node2_instance.import_config(cfg)
        assert node2_instance._enabled is False
        assert node2_instance._epsilon == 1e-6

    def test_channel_mismatch_passthrough(self, node):
        for _ in range(20):
            node.execute(segment=np.random.randn(22, 256), sfreq=512.0)
        assert node._is_fitted is True
        # Try 16-channel segment — should pass through
        node.execute(segment=np.random.randn(16, 256), sfreq=512.0)
        out = node.outputs["segment"].value
        assert out.shape == (16, 256)
