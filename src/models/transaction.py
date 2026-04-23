from dataclasses import dataclass

@dataclass
class Transaction:
    date: str
    narration: str
    chq_ref_no: str
    value_dt: str
    withdrawal_amt: str
    deposit_amt: str
    closing_balance: str