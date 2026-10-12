"""The numpy port of Unitree's walking policy, and the observation it is fed."""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

pytest.importorskip("yaml")

from g1sim import assets                                      # noqa: E402
from g1sim.locomotion import (                                # noqa: E402
    LocomotionConfig, build_observation, gravity_orientation)
from g1sim.policy import LstmPolicy                           # noqa: E402


@pytest.fixture(scope="module")
def policy(assets_root):
    return LstmPolicy.load(assets.policy_path(assets_root))


@pytest.fixture(scope="module")
def config(assets_root):
    return LocomotionConfig.from_yaml(assets.locomotion_config(assets_root))


def test_the_archive_holds_the_documented_network(policy):
    assert (policy.input_size, policy.hidden_size, policy.output_size) == (47, 64, 12)
    assert policy.w_ih.shape == (256, 47) and policy.w_hh.shape == (256, 64)
    assert policy.w1.shape == (32, 64) and policy.w2.shape == (12, 32)


def test_the_policy_is_recurrent_and_reset_clears_its_memory(policy):
    """Why reset must zero the state: the same input gives a different action once the
    LSTM has seen something, so a previous episode would leak into the next."""
    policy.reset()
    first = policy(np.zeros(47))
    second = policy(np.zeros(47))
    assert not np.allclose(first, second)
    policy.reset()
    assert np.allclose(policy(np.zeros(47)), first)


def test_the_numpy_port_matches_torchscript(assets_root, policy):
    torch = pytest.importorskip("torch")
    scripted = torch.jit.load(str(assets.policy_path(assets_root)))
    scripted.reset_memory()
    policy.reset()
    rng = np.random.default_rng(0)
    for _ in range(50):
        obs = rng.normal(size=47).astype(np.float32)
        expected = scripted(torch.from_numpy(obs).unsqueeze(0)).detach().numpy().squeeze()
        assert np.allclose(policy(obs), expected, atol=1e-5)


def test_the_config_is_unitrees(config):
    assert config.dt == pytest.approx(0.002) and config.decimation == 10
    assert config.control_dt == pytest.approx(0.02)
    assert (config.num_obs, config.num_actions) == (47, 12)
    assert config.kps.shape == config.kds.shape == config.default_angles.shape == (12,)


def test_gravity_points_down_in_an_upright_body_frame():
    assert np.allclose(gravity_orientation(np.array([1.0, 0, 0, 0])), [0, 0, -1])


def test_the_observation_layout_is_unitrees(config):
    qpos = np.zeros(19)
    qpos[3] = 1.0
    qpos[7:] = config.default_angles + 0.1
    qvel = np.zeros(18)
    qvel[3:6] = (1.0, 2.0, 3.0)
    qvel[6:] = 2.0
    last = np.arange(12, dtype=np.float32)
    obs = build_observation(config, qpos, qvel, np.array([0.5, 0.0, 0.2]), last,
                            physics_steps=100)          # 0.2 s into a 0.8 s gait
    assert np.allclose(obs[0:3], np.array([1, 2, 3]) * config.ang_vel_scale)
    assert np.allclose(obs[3:6], [0, 0, -1])
    assert np.allclose(obs[6:9], np.array([0.5, 0.0, 0.2]) * config.cmd_scale)
    assert np.allclose(obs[9:21], 0.1 * config.dof_pos_scale)
    assert np.allclose(obs[21:33], 2.0 * config.dof_vel_scale)
    assert np.allclose(obs[33:45], last)
    assert np.allclose(obs[45:47], [1.0, 0.0], atol=1e-6)       # sin, cos at phase 1/4
