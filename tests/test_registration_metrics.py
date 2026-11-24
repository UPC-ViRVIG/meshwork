"""Run with: python -m unittest discover -s tests -p test_registration_metrics.py.

The optimizer is scripted so each scale-search branch is deterministic. Point
cloud sampling and final evaluation use Open3D; an independent NumPy nearest-
neighbour calculation checks the metrics of the returned object transform.
"""

import copy
import json
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import open3d as o3d

from core import pointcloud


def transform_points(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def cloud(points):
    result = o3d.geometry.PointCloud()
    result.points = o3d.utility.Vector3dVector(points)
    return result


def object_transform(location=(0, 0, 0), rotation=(0, 0, 0), scale=1.0):
    return {
        'location': np.array(location, dtype=float),
        'rotation': np.array(rotation, dtype=float),
        'scale': np.full(3, scale, dtype=float),
    }


class RegistrationMetricsTests(unittest.TestCase):
    def test_returned_transform_metrics_on_unchanged_final_samples(self):
        identity = object_transform()
        moved_source = object_transform((0.08, -0.05, 0.03), (0.1, -0.2, 0.05), 1.1)
        moved_target = object_transform((-0.06, 0.02, 0.04), (-0.15, 0.08, 0.12), 1.3)
        cases = [
            ('last_scale_changes', [0.99, 1.03, 1.01], True, False,
             identity, identity, [0.8, 1.5], 1.029897),
            ('last_scale_unchanged', [0.99, 1.01, 1.0], True, False,
             identity, identity, [0.8, 1.5], 0.9999),
            ('scale_search_disabled', [1.0, 1.0, 1.0], False, False,
             identity, identity, [0.8, 1.5], 1.0),
            ('uncentred_source', [0.99, 1.03, 1.01], True, True,
             identity, identity, [0.8, 1.5], 1.029897),
            ('nonidentity_object_transforms', [0.99, 1.03, 1.01], True, True,
             moved_source, moved_target, [0.8, 1.5], 1.029897),
            ('nonidentity_without_scale_search', [1.0, 1.0, 1.0], False, True,
             moved_source, moved_target, [0.8, 1.5], 1.0),
            ('sampling_uses_actual_not_clipped_scales', [0.95, 0.95, 0.95], True, True,
             moved_source, moved_target, [0.99, 1.01], 0.99),
        ]
        for case in cases:
            with self.subTest(case=case[0]):
                self.check_case(*case[1:])

    def check_case(self, steps, search_enabled, uncentred, source_transform,
                   target_transform, clip, expected_scale_factor):
        # Avoid application configuration and file logging under the user's home.
        logger = logging.Logger('meshwork.registration_metrics_test')
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        with patch.object(pointcloud, 'get_logger', return_value=logger):
            api = pointcloud.PointcloudAPI()

        rng = np.random.default_rng(1701)
        source_points = rng.uniform(-0.5, 0.5, size=(512, 3))
        source_points -= source_points.mean(axis=0)
        if uncentred:
            source_points += np.array([2.0, -1.0, 3.0])

        compose = api._compose_transform_matrix
        source_matrix = compose(**source_transform)
        target_matrix = compose(**target_transform)
        expected_returned_matrix = compose(
            source_transform['location'], source_transform['rotation'],
            source_transform['scale'] * expected_scale_factor)
        # Deliberately omit some target points and add a small, known offset.
        # This exercises both the fitness denominator and a nonzero RMSE.
        target_points = transform_points(
            source_points[:-51], np.linalg.inv(target_matrix) @ expected_returned_matrix)
        target_points += np.array([0.0007, -0.0003, 0.0002])

        config = copy.deepcopy(pointcloud.ALIGN_CONFIG)
        config.update(estimate_scale=search_enabled, scale_clip=clip, voxel_divisor=20)
        candidates = config['scale_candidates'] if search_enabled else []
        calls_per_level = 1 + len(candidates)
        icp_calls = []
        last_level = {}

        def result(rmse, matrix=None):
            return SimpleNamespace(
                fitness=0.4, inlier_rmse=rmse,
                transformation=np.eye(4) if matrix is None else matrix)

        def scripted_icp(source, target, threshold, initial, estimator, criteria):
            call = len(icp_calls)
            icp_calls.append(criteria.max_iteration)
            if call < 2:
                return result(0.3 if call == 0 else 0.2)
            level, trial = divmod(call - 2, calls_per_level)
            if trial == 0:
                if level == 2:
                    last_level.update(source=source, target=target, threshold=threshold)
                return result(0.2)
            # The best trial has a different pose. It must remain unused, just
            # as in v1.0.1: this fix must not adopt or rerun trial ICP transforms.
            trial_matrix = np.eye(4)
            trial_matrix[:3, 3] = [10.0, 20.0, 30.0]
            wins = candidates[trial - 1] == steps[level]
            return result(0.05 if wins else 0.3, trial_matrix)

        registration = o3d.pipelines.registration
        real_evaluate = registration.evaluate_registration
        with tempfile.TemporaryDirectory(prefix='meshwork-registration-test-') as directory:
            source_path, target_path = [Path(directory) / name for name in ('source.ply', 'target.ply')]
            self.assertTrue(o3d.io.write_point_cloud(str(source_path), cloud(source_points)))
            self.assertTrue(o3d.io.write_point_cloud(str(target_path), cloud(target_points)))
            with patch.dict(pointcloud.ALIGN_CONFIG, config, clear=True), \
                    patch.object(registration, 'compute_fpfh_feature',
                                 return_value=SimpleNamespace(dimension=lambda: 33)), \
                    patch.object(registration, 'registration_ransac_based_on_feature_matching',
                                 return_value=result(0.2)), \
                    patch.object(registration, 'registration_icp', side_effect=scripted_icp), \
                    patch.object(registration, 'evaluate_registration', wraps=real_evaluate) as evaluate:
                actual = api._compute_alignment(
                    source_path, target_path, source_transform, target_transform)

        # Identity main-ICP transforms must leave the existing object pose
        # unchanged. Only the pre-existing scale-selection logic changes scale.
        np.testing.assert_allclose(actual['location'], source_transform['location'], atol=1e-12)
        np.testing.assert_allclose(actual['rotation'], source_transform['rotation'], atol=1e-12)
        np.testing.assert_allclose(actual['scale'],
                                   source_transform['scale'] * expected_scale_factor, atol=1e-12)
        expected_calls = [10, 10] + [
            iterations for _ in steps
            for iterations in ([config['icp_max_iteration']]
                               + [config['scale_test_iteration']] * len(candidates))
        ]
        self.assertEqual(icp_calls, expected_calls)
        evaluate.assert_called_once()
        self.assertIs(evaluate.call_args.args[0], last_level['source'])
        self.assertIs(evaluate.call_args.args[1], last_level['target'])
        self.assertEqual(evaluate.call_args.args[2], last_level['threshold'])

        evaluation = actual['registration']['evaluation']
        voxel_size = evaluation['voxel_size']
        # Reconstruct voxel memberships geometrically, without using the
        # implementation's inverse sampling matrix to calculate the oracle.
        sampled_coordinates = transform_points(
            source_points, np.linalg.inv(target_matrix) @ source_matrix)
        for scale in steps[:-1]:
            if scale != 1.0:
                center = sampled_coordinates.mean(axis=0)
                sampled_coordinates = scale * (sampled_coordinates - center) + center
        voxel_origin = sampled_coordinates.min(axis=0) - 0.5 * voxel_size
        voxel_indices = np.floor((sampled_coordinates - voxel_origin) / voxel_size).astype(int)
        groups = {}
        for index, voxel in enumerate(voxel_indices):
            groups.setdefault(tuple(voxel), []).append(index)
        raw_centroids = np.array([source_points[indices].mean(axis=0) for indices in groups.values()])
        expected_points = transform_points(
            raw_centroids, np.linalg.inv(target_matrix) @ expected_returned_matrix)
        target_samples = np.asarray(last_level['target'].points)
        distance_squared = ((expected_points[:, None, :] - target_samples[None, :, :]) ** 2).sum(axis=2).min(axis=1)
        inliers = distance_squared <= last_level['threshold'] ** 2
        expected_fitness = float(inliers.mean())
        expected_rmse = float(np.sqrt(distance_squared[inliers].mean())) if inliers.any() else 0.0
        self.assertGreater(expected_fitness, 0.5)
        self.assertLess(expected_fitness, 1.0)
        self.assertGreater(expected_rmse, 0.0)
        self.assertAlmostEqual(actual['fitness'], expected_fitness, places=12)
        self.assertAlmostEqual(actual['rmse'], expected_rmse, places=12)

        np.testing.assert_allclose(
            transform_points(source_points, np.array(evaluation['source_sampling_transform'])),
            sampled_coordinates, atol=1e-12)
        np.testing.assert_allclose(evaluation['returned_source_transform'], expected_returned_matrix, atol=1e-12)
        np.testing.assert_allclose(evaluation['source_input_transform'], source_matrix, atol=1e-12)
        np.testing.assert_allclose(evaluation['target_input_transform'], target_matrix, atol=1e-12)
        self.assertEqual(evaluation['source_points'], len(raw_centroids))
        self.assertEqual(evaluation['target_points'], len(target_samples))
        self.assertEqual(evaluation['correspondences'], int(inliers.sum()))
        self.assertEqual(evaluation['max_correspondence_distance'], 2.0 * voxel_size)
        self.assertEqual(evaluation['coordinate_frame'], 'target_local')
        self.assertEqual(evaluation['distance_units'], 'target_local_scene_units')
        self.assertEqual(actual['registration']['level_metric_semantics']['fitness'], 'icp_before_scale_search')
        self.assertEqual(actual['registration']['levels'][-1]['fitness'], 0.4)
        self.assertEqual(actual['registration']['levels'][-1]['inlier_rmse'], 0.2)
        json.dumps(actual['registration'])  # Evaluation metadata is persistable.


if __name__ == '__main__':
    unittest.main()
