# tests/test_tsfbcsp_features.py
"""Tests for BCI_TSFBCSPFeatures node and its pure helper functions."""
import numpy as np
import pytest


# ---------- Pure function tests ----------

class TestOASShrinkage:
    def test_output_shape(self):
        from plugins.bci_tsfbcsp_features_node import _oas_shrinkage
        X = np.random.randn(22, 256)
        C = _oas_shrinkage(X)
        assert C.shape == (22, 22)

    def test_symmetric(self):
        from plugins.bci_tsfbcsp_features_node import _oas_shrinkage
        X = np.random.randn(22, 256)
        C = _oas_shrinkage(X)
        np.testing.assert_allclose(C, C.T, atol=1e-12)

    def test_positive_definite(self):
        from plugins.bci_tsfbcsp_features_node import _oas_shrinkage
        X = np.random.randn(22, 256)
        C = _oas_shrinkage(X)
        eigvals = np.linalg.eigvalsh(C)
        assert np.all(eigvals > 0)

    def test_few_samples(self):
        from plugins.bci_tsfbcsp_features_node import _oas_shrinkage
        X = np.random.randn(22, 1)
        C = _oas_shrinkage(X)
        assert C.shape == (22, 22)
        np.testing.assert_allclose(C, C.T, atol=1e-12)


class TestFilterBands:
    def test_returns_correct_count(self):
        from plugins.bci_tsfbcsp_features_node import _apply_filter_bands, DEFAULT_FILTER_BANK
        seg = np.random.randn(22, 512)
        sfreq = 256.0
        filtered = _apply_filter_bands(seg, sfreq, DEFAULT_FILTER_BANK)
        assert len(filtered) == len(DEFAULT_FILTER_BANK)

    def test_preserves_shape(self):
        from plugins.bci_tsfbcsp_features_node import _apply_filter_bands, DEFAULT_FILTER_BANK
        seg = np.random.randn(22, 512)
        sfreq = 256.0
        filtered = _apply_filter_bands(seg, sfreq, DEFAULT_FILTER_BANK)
        for f in filtered:
            assert f.shape == seg.shape


class TestRiemannianMean:
    def test_single_cov(self):
        from plugins.bci_tsfbcsp_features_node import _riemannian_mean
        C = np.eye(5) + np.random.randn(5, 5) * 0.1
        C = 0.5 * (C + C.T)
        M = _riemannian_mean([C])
        np.testing.assert_allclose(M, C, atol=1e-10)

    def test_multiple_covs(self):
        from plugins.bci_tsfbcsp_features_node import _riemannian_mean
        covs = []
        for _ in range(5):
            C = np.eye(5) + np.random.randn(5, 5) * 0.1
            C = 0.5 * (C + C.T)
            C = C @ C.T  # make SPD
            covs.append(C)
        M = _riemannian_mean(covs)
        assert M.shape == (5, 5)
        np.testing.assert_allclose(M, M.T, atol=1e-10)
        eigvals = np.linalg.eigvalsh(M)
        assert np.all(eigvals > 0)

    def test_convergence(self):
        from plugins.bci_tsfbcsp_features_node import _riemannian_mean
        # Create covs close to each other — should converge fast
        base = np.eye(3) + np.array([[0.5, 0.1, 0], [0.1, 0.5, 0.1], [0, 0.1, 0.5]])
        covs = [base + np.random.randn(3, 3) * 0.01 for _ in range(10)]
        covs = [0.5 * (C + C.T) for C in covs]
        covs = [C @ C.T for C in covs]  # make SPD
        M = _riemannian_mean(covs, max_iter=100, tol=1e-8)
        assert M is not None
        assert M.shape == (3, 3)


class TestLogMap:
    def test_identity(self):
        from plugins.bci_tsfbcsp_features_node import _log_map
        M = np.eye(5)
        C = np.eye(5)
        log_MC = _log_map(M, C)
        np.testing.assert_allclose(log_MC, np.zeros((5, 5)), atol=1e-6)

    def test_symmetric_output(self):
        from plugins.bci_tsfbcsp_features_node import _log_map
        M = np.eye(5)
        C = np.diag([1.0, 2.0, 3.0, 4.0, 5.0])
        log_MC = _log_map(M, C)
        np.testing.assert_allclose(log_MC, log_MC.T, atol=1e-10)


class TestVectorizeUpper:
    def test_length(self):
        from plugins.bci_tsfbcsp_features_node import _vectorize_upper
        n = 5
        vec = _vectorize_upper(np.eye(n))
        expected_len = n * (n + 1) // 2
        assert len(vec) == expected_len

    def test_diagonal_preserved(self):
        from plugins.bci_tsfbcsp_features_node import _vectorize_upper
        M = np.diag([1.0, 2.0, 3.0])
        vec = _vectorize_upper(M)
        # triu_indices(3) → (0,0),(0,1),(0,2),(1,1),(1,2),(2,2)
        # diagonal entries: positions 0, 3, 5
        assert vec[0] == 1.0
        assert vec[3] == 2.0
        assert vec[5] == 3.0

    def test_offdiagonal_scaled(self):
        from plugins.bci_tsfbcsp_features_node import _vectorize_upper
        M = np.array([[1.0, 0.5], [0.5, 2.0]])
        vec = _vectorize_upper(M)
        # triu_indices(2) → (0,0),(0,1),(1,1)
        # → [1.0, 0.5*sqrt(2), 2.0]
        np.testing.assert_allclose(vec, [1.0, 0.5 * np.sqrt(2), 2.0], atol=1e-12)


# ---------- Plugin node tests ----------

class TestBCITSFBCSPFeatures:
    @pytest.fixture
    def node(self):
        from plugins.bci_tsfbcsp_features_node import BCITSFBCSPFeatures
        n = BCITSFBCSPFeatures()
        n.setup()
        return n

    def test_setup_creates_inputs_outputs(self, node):
        assert "segment" in node.inputs
        assert "sfreq" in node.inputs
        assert "features" in node.outputs
        assert "features_dim" in node.outputs

    def test_execute_no_segment_returns_empty(self, node):
        result = node.execute(segment=None, sfreq=256.0)
        assert result == {}

    def test_fit_mode_accumulates(self, node):
        node._mode = "fit"
        seg = np.random.randn(22, 256)
        node.execute(segment=seg, sfreq=256.0, y_idx=0)
        assert len(node._fit_labels) == 1
        assert len(node._fit_covs_per_band[0]) == 1

    def test_fit_mode_multiple_bands(self, node):
        node._mode = "fit"
        seg = np.random.randn(22, 256)
        node.execute(segment=seg, sfreq=256.0, y_idx=0)
        assert len(node._fit_covs_per_band) == 9  # 9 filter bands

    def _do_fit(self, node):
        """Fit Riemannian means without needing UI widgets."""
        from plugins.bci_tsfbcsp_features_node import _riemannian_mean
        if len(node._fit_labels) < 2:
            raise ValueError("Need >=2 labeled segments")
        means = []
        for b_idx in range(node._n_bands):
            covs = node._fit_covs_per_band[b_idx]
            if len(covs) < 2:
                means.append(np.eye(node._n_ch))
                continue
            M = _riemannian_mean(covs)
            if M is None:
                M = np.eye(node._n_ch)
            means.append(M)
        node._riemannian_means = means
        node._is_fitted = True
        # Fit StandardScaler if available
        try:
            from sklearn.preprocessing import StandardScaler
            if len(node._fit_labels) > 0:
                train_feats = []
                for trial_idx in range(len(node._fit_labels)):
                    feat_vec = node._extract_features_per_trial(trial_idx)
                    if feat_vec is not None:
                        train_feats.append(feat_vec)
                if len(train_feats) > 1:
                    train_X = np.stack(train_feats, axis=0)
                    node._scaler = StandardScaler()
                    node._scaler.fit(train_X)
        except Exception:
            pass

    def test_fit_then_transform(self, node):
        # Accumulate 10 training segments
        node._mode = "fit"
        for i in range(10):
            seg = np.random.randn(22, 256)
            node.execute(segment=seg, sfreq=256.0, y_idx=i % 2)

        # Manually trigger fit
        self._do_fit(node)
        assert node._is_fitted is True

        # Now transform
        node._mode = "transform"
        test_seg = np.random.randn(22, 256)
        node.execute(segment=test_seg, sfreq=256.0)

        features = node.outputs["features"].value
        assert features is not None
        assert features.ndim == 1

    def test_feature_dimensionality(self, node):
        n_ch = 22
        n_bands = 9
        expected_dim = n_ch * (n_ch + 1) // 2 * n_bands  # 253 * 9 = 2277

        node._mode = "fit"
        for i in range(10):
            seg = np.random.randn(n_ch, 256)
            node.execute(segment=seg, sfreq=256.0, y_idx=i % 2)
        self._do_fit(node)

        node._mode = "transform"
        node.execute(segment=np.random.randn(n_ch, 256), sfreq=256.0)

        features = node.outputs["features"].value
        assert features.shape[0] == expected_dim

    def test_band_labels_output(self, node):
        node._mode = "fit"
        for i in range(5):
            node.execute(segment=np.random.randn(22, 256), sfreq=256.0, y_idx=i % 2)
        self._do_fit(node)

        node._mode = "transform"
        node.execute(segment=np.random.randn(22, 256), sfreq=256.0)

        labels = node.outputs["band_labels"].value
        assert labels is not None
        assert len(labels) == 9

    def test_covariances_output(self, node):
        node._mode = "fit"
        for i in range(5):
            node.execute(segment=np.random.randn(22, 256), sfreq=256.0, y_idx=i % 2)

        covs = node.outputs["covariances"].value
        assert covs is not None
        assert len(covs) == 9

    def test_export_import_config(self, node):
        node._mode = "fit"
        node._cov_estimator = "empirical"
        cfg = node.export_config()
        assert cfg["mode"] == "fit"
        assert cfg["cov_estimator"] == "empirical"

        from plugins.bci_tsfbcsp_features_node import BCITSFBCSPFeatures
        node2 = BCITSFBCSPFeatures()
        node2.setup()
        node2.import_config(cfg)
        assert node2._mode == "fit"
        assert node2._cov_estimator == "empirical"

    def test_transform_before_fit_returns_none(self, node):
        node._mode = "transform"
        node.execute(segment=np.random.randn(22, 256), sfreq=256.0)
        assert node.outputs["features"].value is None

    def test_inference_latency(self, node):
        """Verify single-trial inference is fast (<100ms)."""
        import time
        node._mode = "fit"
        for i in range(10):
            node.execute(segment=np.random.randn(22, 256), sfreq=256.0, y_idx=i % 2)
        self._do_fit(node)

        node._mode = "transform"
        start = time.perf_counter()
        node.execute(segment=np.random.randn(22, 256), sfreq=256.0)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"Inference took {elapsed_ms:.1f}ms, expected <100ms"
