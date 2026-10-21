"""Application service for cluster lifecycle."""

from __future__ import annotations

from justkernel.application.ports import ClusterRepositoryPort, IdFactoryPort
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.ids import AgentId, CandidateId, ClusterId


# ---- ClusterService ---------------------------------------------------------
class ClusterService:
    def __init__(self, clusters: ClusterRepositoryPort, ids: IdFactoryPort) -> None:
        self.clusters = clusters
        self.ids = ids

    def create_cluster(
        self,
        *,
        operator_id: str,
        supervisor_id: AgentId,
        operator_spec_ref: OperatorRef,
        start_mode: StartMode,
        max_agents: int = 100,
        created_at: int,
        continued_from_cluster_id: ClusterId | None = None,
    ) -> Cluster:
        cluster = Cluster(
            id=self.ids.cluster_id(),
            operator_id=operator_id,
            supervisor_id=supervisor_id,
            operator_spec_ref=operator_spec_ref,
            start_mode=start_mode,
            max_agents=max_agents,
            created_at=created_at,
            continued_from_cluster_id=continued_from_cluster_id,
        )
        self.clusters.insert(cluster)
        return cluster

    def get(self, cluster_id: ClusterId) -> Cluster:
        return self.clusters.get(cluster_id)

    def start_cluster(self, cluster_id: ClusterId) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.start()
        return self._update(cluster)

    def pause_cluster(self, cluster_id: ClusterId) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.pause()
        return self._update(cluster)

    def resume_cluster(self, cluster_id: ClusterId) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.resume()
        return self._update(cluster)

    def establish_baseline(self, cluster_id: ClusterId, candidate_id: CandidateId) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.establish_baseline(candidate_id)
        return self._update(cluster)

    def converge_cluster(self, cluster_id: ClusterId) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.converge()
        return self._update(cluster)

    def stop_cluster(self, cluster_id: ClusterId, reason: str, now_ms: int) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.stop(reason, now_ms)
        return self._update(cluster)

    def set_max_agents(self, cluster_id: ClusterId, max_agents: int) -> Cluster:
        cluster = self.get(cluster_id)
        cluster.set_max_agents(max_agents)
        return self._update(cluster)

    def _update(self, cluster: Cluster) -> Cluster:
        version = self.clusters.version(cluster.id)
        self.clusters.update(cluster, expected_version=version)
        return cluster
