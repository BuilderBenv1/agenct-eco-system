import json
from pathlib import Path
from web3 import Web3
from eth_account import Account
from shared.config import settings
from shared.web3_client import w3

ABI_DIR = Path(__file__).parent / "abis"


def _load_abi(name: str) -> list:
    with open(ABI_DIR / f"{name}.json") as f:
        return json.load(f)


class AgentRegistryContract:
    def __init__(self):
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.AGENT_REGISTRY_ADDRESS),
            abi=_load_abi("AgentRegistry"),
        )

    def is_agent_active(self, nft_token_id: int) -> bool:
        return self.contract.functions.isAgentActive(nft_token_id).call()

    def get_agent_tba(self, nft_token_id: int) -> str:
        return self.contract.functions.getAgentTBA(nft_token_id).call()

    def get_erc8004_id(self, nft_token_id: int) -> int:
        return self.contract.functions.getERC8004Id(nft_token_id).call()

    def get_registered_agents(self) -> list[int]:
        return self.contract.functions.getRegisteredAgents().call()


class SubscriptionManagerContract:
    def __init__(self):
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.SUBSCRIPTION_MANAGER_ADDRESS),
            abi=_load_abi("SubscriptionManager"),
        )

    def has_active_subscription(self, subscriber: str, plan_id: int) -> bool:
        return self.contract.functions.hasActiveSubscription(
            Web3.to_checksum_address(subscriber), plan_id
        ).call()

    def get_plan(self, plan_id: int) -> dict:
        result = self.contract.functions.getPlan(plan_id).call()
        return {
            "agent": result[0],
            "pricePerPeriod": result[1],
            "periodDuration": result[2],
            "active": result[3],
            "name": result[4],
        }

    def get_agent_plans(self, agent_tba: str) -> list[int]:
        return self.contract.functions.getAgentPlans(
            Web3.to_checksum_address(agent_tba)
        ).call()


class AgentProofOracleContract:
    def __init__(self):
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.AGENT_PROOF_ORACLE_ADDRESS),
            abi=_load_abi("AgentProofOracle"),
        )
        if settings.ORACLE_PRIVATE_KEY:
            self.account = Account.from_key(settings.ORACLE_PRIVATE_KEY)
        else:
            self.account = None

    def submit_proof(
        self,
        agent_id: int,
        score: int,
        score_decimals: int,
        tag1: str,
        tag2: str,
        proof_uri: str,
        proof_hash: bytes,
    ) -> str:
        """Submit a proof on-chain. Returns tx hash."""
        if not self.account:
            raise RuntimeError("ORACLE_PRIVATE_KEY not configured")
        nonce = w3.eth.get_transaction_count(self.account.address)
        tx = self.contract.functions.submitProof(
            agent_id, score, score_decimals, tag1, tag2, proof_uri, proof_hash
        ).build_transaction({
            "from": self.account.address,
            "nonce": nonce,
            "gas": 300_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": settings.CHAIN_ID,
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    def get_latest_proof(self, agent_id: int) -> dict:
        result = self.contract.functions.getLatestProof(agent_id).call()
        return {
            "agentId": result[0],
            "score": result[1],
            "scoreDecimals": result[2],
            "tag1": result[3],
            "tag2": result[4],
            "proofURI": result[5],
            "proofHash": result[6].hex(),
            "timestamp": result[7],
            "oracle": result[8],
        }

    def get_proof_count(self, agent_id: int) -> int:
        return self.contract.functions.getProofCount(agent_id).call()


class EscrowContract:
    def __init__(self):
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.ESCROW_ADDRESS),
            abi=_load_abi("Escrow"),
        )

    def get_escrow(self, escrow_id: int) -> dict:
        result = self.contract.functions.getEscrow(escrow_id).call()
        return {
            "client": result[0],
            "agent": result[1],
            "amount": result[2],
            "createdAt": result[3],
            "deadline": result[4],
            "status": result[5],
            "serviceHash": result[6].hex(),
        }

    def get_client_escrows(self, client: str) -> list[int]:
        return self.contract.functions.getClientEscrows(
            Web3.to_checksum_address(client)
        ).call()


# Singleton instances
agent_registry = AgentRegistryContract()
subscription_manager = SubscriptionManagerContract()
proof_oracle = AgentProofOracleContract()
escrow_contract = EscrowContract()
