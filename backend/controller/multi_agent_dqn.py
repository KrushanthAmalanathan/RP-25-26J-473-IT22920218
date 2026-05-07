from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
except ImportError as e:
    raise ImportError(
        "PyTorch is required but not installed. "
        "Install it with: pip install torch torchvision torchaudio"
    ) from e


# =========================
# Priority Weights (Sri Lanka-aware)
# =========================
# Bus gets slightly higher priority than truck/lorry because it carries more passengers
DEFAULT_VEHICLE_WEIGHTS = {
    "bike": 1.0,
    "car": 2.0,
    "auto": 2.0,     # 3-wheeler
    "bus": 5.0,      # higher priority
    "truck": 4.0,
    "lorry": 4.0,
}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def now_ts() -> float:
    return time.time()


@dataclass
class Transition:
    s: List[float]
    a: int
    r: float
    s2: List[float]
    done: bool


class ReplayBuffer:
    def __init__(self, capacity: int = 50_000):
        self.capacity = capacity
        self.buf: List[Transition] = []
        self.i = 0

    def add(self, t: Transition) -> None:
        if len(self.buf) < self.capacity:
            self.buf.append(t)
        else:
            self.buf[self.i] = t
        self.i = (self.i + 1) % self.capacity

    def sample(self, batch_size: int) -> List[Transition]:
        return random.sample(self.buf, k=min(batch_size, len(self.buf)))

    def __len__(self) -> int:
        return len(self.buf)


# =========================
# DQN Model
# =========================
class TinyMLP(nn.Module):
    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
            nn.Linear(128, out_dim),
        )

    def forward(self, x):
        return self.net(x)


class DQNAgent:
    """
    Independent DQN agent for ONE junction.

    Action space: discrete (e.g., choose which approach/phase to serve next).
    Duration: computed by stable heuristic from the selected approach weighted queue.
    """

    def __init__(
        self,
        agent_name: str,
        state_dim: int,
        action_dim: int,
        gamma: float = 0.95,
        lr: float = 1e-3,
        epsilon_start: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.999,
        target_update_every: int = 200,
        batch_size: int = 64,
        replay_capacity: int = 50_000,
        device: str = "cpu",
        min_green: int = 10,
        max_green: int = 45,
        duration_scale: float = 0.7,
        duration_base: int = 10,
    ):
        if torch is None:
            raise RuntimeError(
                "PyTorch not installed. Install 'torch' to use DQNAgent."
            )

        self.name = agent_name
        self.state_dim = state_dim
        self.action_dim = action_dim

        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay

        self.batch_size = batch_size
        self.target_update_every = target_update_every
        self.train_steps = 0

        self.min_green = min_green
        self.max_green = max_green
        self.duration_scale = duration_scale
        self.duration_base = duration_base

        self.device = torch.device(device)

        self.q = TinyMLP(state_dim, action_dim).to(self.device)
        self.target = TinyMLP(state_dim, action_dim).to(self.device)
        self.target.load_state_dict(self.q.state_dict())
        self.target.eval()

        self.optim = optim.Adam(self.q.parameters(), lr=lr)
        self.loss_fn = nn.MSELoss()

        self.replay = ReplayBuffer(capacity=replay_capacity)

    def select_action(self, state: List[float], valid_actions: Optional[List[int]] = None) -> int:
        if valid_actions is None:
            valid_actions = list(range(self.action_dim))

        if random.random() < self.epsilon:
            return random.choice(valid_actions)

        with torch.no_grad():
            s = torch.tensor(state, dtype=torch.float32, device=self.device).unsqueeze(0)
            qvals = self.q(s).squeeze(0).cpu().tolist()

        best_a = max(valid_actions, key=lambda a: qvals[a])
        return best_a

    def compute_duration(self, weighted_queue_selected: float) -> int:
        dur = int(self.duration_base + weighted_queue_selected * self.duration_scale)
        return int(clamp(dur, self.min_green, self.max_green))

    def remember(self, s: List[float], a: int, r: float, s2: List[float], done: bool) -> None:
        self.replay.add(Transition(s=s, a=a, r=r, s2=s2, done=done))

    def train_step(self) -> Optional[float]:
        if len(self.replay) < self.batch_size:
            self._decay_epsilon()
            return None

        batch = self.replay.sample(self.batch_size)

        s = torch.tensor([t.s for t in batch], dtype=torch.float32, device=self.device)
        a = torch.tensor([t.a for t in batch], dtype=torch.int64, device=self.device).unsqueeze(1)
        r = torch.tensor([t.r for t in batch], dtype=torch.float32, device=self.device).unsqueeze(1)
        s2 = torch.tensor([t.s2 for t in batch], dtype=torch.float32, device=self.device)
        done = torch.tensor([t.done for t in batch], dtype=torch.float32, device=self.device).unsqueeze(1)

        q_sa = self.q(s).gather(1, a)

        with torch.no_grad():
            q_next = self.target(s2).max(dim=1, keepdim=True)[0]
            y = r + (1.0 - done) * self.gamma * q_next

        loss = self.loss_fn(q_sa, y)

        self.optim.zero_grad()
        loss.backward()
        self.optim.step()

        self.train_steps += 1
        if self.train_steps % self.target_update_every == 0:
            self.target.load_state_dict(self.q.state_dict())

        self._decay_epsilon()
        return float(loss.detach().cpu().item())

    def _decay_epsilon(self) -> None:
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)


# =========================
# Multi-Agent Manager (Option 3)
# =========================
class MultiAgentManager:
    """
    Option-3 Multi-Agent DQN:
    - 3 different junctions supported via config
    - priority-weighted queues (Sri Lanka weights)
    - emergency override BEFORE DQN (hard rule)
    - returns metrics for dashboard
    """

    def __init__(
        self,
        junction_config: Dict[str, Dict[str, Any]],
        vehicle_weights: Optional[Dict[str, float]] = None,
        normalize_queue_by: float = 100.0,
        device: str = "cpu",
    ):
        if torch is None:
            raise RuntimeError("PyTorch not installed. Install torch to use MultiAgentManager.")

        self.cfg = junction_config
        self.weights = vehicle_weights or DEFAULT_VEHICLE_WEIGHTS
        self.normalize_queue_by = max(1.0, float(normalize_queue_by))
        self.device = device

        self.agents: Dict[str, DQNAgent] = {}

        # for transitions
        self.last_obs: Dict[str, Dict[str, Any]] = {}
        self.last_state: Dict[str, List[float]] = {}
        self.last_action: Dict[str, int] = {}

        for junc_id, jc in self.cfg.items():
            self.agents[junc_id] = DQNAgent(
                agent_name=f"DQN_{junc_id}",
                state_dim=jc["state_dim"],
                action_dim=jc["action_dim"],
                device=self.device,
                gamma=jc.get("gamma", 0.95),
                lr=jc.get("lr", 1e-3),
                epsilon_start=jc.get("epsilon_start", 1.0),
                epsilon_min=jc.get("epsilon_min", 0.05),
                epsilon_decay=jc.get("epsilon_decay", 0.999),
                target_update_every=jc.get("target_update_every", 200),
                batch_size=jc.get("batch_size", 64),
                replay_capacity=jc.get("replay_capacity", 50_000),
                min_green=jc.get("min_green", 10),
                max_green=jc.get("max_green", 45),
                duration_scale=jc.get("duration_scale", 0.7),
                duration_base=jc.get("duration_base", 10),
            )

    # ---- priority weighted queue ----
    def weighted_queue(self, counts_by_type: Dict[str, int]) -> float:
        total = 0.0
        for vtype, cnt in counts_by_type.items():
            total += float(cnt) * float(self.weights.get(vtype, 1.0))
        return total

    # ---- build state ----
    def build_state(self, junc_id: str, obs: Dict[str, Any]) -> List[float]:
        jc = self.cfg[junc_id]
        approach_keys: List[str] = jc["approach_keys"]

        # weighted queues normalized
        queues = []
        for k in approach_keys:
            by_type = obs.get("approaches", {}).get(k, {})
            q = self.weighted_queue(by_type)
            queues.append(q / self.normalize_queue_by)

        # current green one-hot
        g_len = jc["green_onehot_len"]
        g = [0.0] * g_len
        idx = int(obs.get("current_green_index", 0))
        if 0 <= idx < g_len:
            g[idx] = 1.0

        # remaining green normalized
        rem = float(obs.get("remaining_green", 0.0))
        rem_norm = rem / float(jc.get("max_green", 45))

        state = queues + g + [rem_norm]

        # pad/trim to exact size
        while len(state) < jc["state_dim"]:
            state.append(0.0)
        return state[: jc["state_dim"]]

    # ---- reward ----
    def compute_reward(self, junc_id: str, prev_obs: Dict[str, Any], new_obs: Dict[str, Any], action_idx: int) -> float:
        jc = self.cfg[junc_id]
        approach_keys = jc["approach_keys"]

        def qvec(o: Dict[str, Any]) -> List[float]:
            out = []
            for k in approach_keys:
                out.append(self.weighted_queue(o.get("approaches", {}).get(k, {})))
            return out

        before = qvec(prev_obs)
        after = qvec(new_obs)

        acted = int(clamp(int(action_idx), 0, len(before) - 1))

        acted_reduction = before[acted] - after[acted]
        inc = []
        for i in range(len(before)):
            if i == acted:
                continue
            inc.append(max(0.0, after[i] - before[i]))
        avg_inc_other = (sum(inc) / len(inc)) if inc else 0.0

        return float(acted_reduction - 0.5 * avg_inc_other)

    # ---- main decide ----
    def decide(self, junc_id: str, obs: Dict[str, Any]) -> Tuple[int, int, str, Dict[str, Any]]:
        if junc_id not in self.agents:
            raise KeyError(f"Unknown junction_id={junc_id}")

        jc = self.cfg[junc_id]
        agent = self.agents[junc_id]

        # 1) emergency override always wins
        if bool(obs.get("emergency", False)) is True:
            em_idx = int(obs.get("emergency_index", 0))
            em_idx = int(clamp(em_idx, 0, jc["action_dim"] - 1))
            duration = int(jc.get("emergency_green", jc.get("max_green", 45)))

            metrics = {
                "timestamp": now_ts(),
                "junction_id": junc_id,
                "mode": "emergency_override",
                "selected_action": em_idx,
                "duration": duration,
                "epsilon": agent.epsilon,
            }

            # update last for next reward calc
            self.last_obs[junc_id] = obs
            self.last_state[junc_id] = self.build_state(junc_id, obs)
            self.last_action[junc_id] = em_idx
            return em_idx, duration, "Emergency override", metrics

        # 2) build state
        state = self.build_state(junc_id, obs)

        # 3) reward + training using previous step
        reward_prev = None
        loss = None
        if junc_id in self.last_obs:
            prev_obs = self.last_obs[junc_id]
            prev_state = self.last_state[junc_id]
            prev_action = self.last_action[junc_id]

            reward_prev = self.compute_reward(junc_id, prev_obs, obs, prev_action)
            agent.remember(prev_state, prev_action, reward_prev, state, done=False)
            loss = agent.train_step()

        # 4) choose action
        valid_actions = jc.get("valid_actions")
        a = agent.select_action(state, valid_actions=valid_actions)

        # 5) duration heuristic based on selected approach queue
        approach_keys = jc["approach_keys"]
        sel_key = approach_keys[int(clamp(a, 0, len(approach_keys) - 1))]
        sel_queue = self.weighted_queue(obs.get("approaches", {}).get(sel_key, {}))
        duration = agent.compute_duration(sel_queue)

        # 6) update last
        self.last_obs[junc_id] = obs
        self.last_state[junc_id] = state
        self.last_action[junc_id] = a

        metrics = {
            "timestamp": now_ts(),
            "junction_id": junc_id,
            "mode": "dqn",
            "selected_action": a,
            "duration": duration,
            "epsilon": agent.epsilon,
            "reward_prev": reward_prev,
            "loss": loss,
        }

        return a, duration, "DQN decision", metrics


def example_junction_config() -> Dict[str, Dict[str, Any]]:
    """
    Replace keys with your real lane/approach mapping (J1/J2/J3).
    If J2 is 3-way junction, keep 3 approach_keys and action_dim=3.
    """
    return {
        "J1": {
            "approach_keys": ["W", "J1N", "J8N", "J8E", "J8S"],
            "action_dim": 5,
            "green_onehot_len": 5,
            "state_dim": 5 + 5 + 1,
            "min_green": 10,
            "max_green": 45,
            "emergency_green": 45,
        },
        "J2": {
            "approach_keys": ["A", "B", "C"],
            "action_dim": 3,
            "green_onehot_len": 3,
            "state_dim": 3 + 3 + 1,
            "min_green": 10,
            "max_green": 40,
            "emergency_green": 40,
        },
        "J3": {
            "approach_keys": ["N", "E", "S", "W"],
            "action_dim": 4,
            "green_onehot_len": 4,
            "state_dim": 4 + 4 + 1,
            "min_green": 10,
            "max_green": 45,
            "emergency_green": 45,
        },
    }