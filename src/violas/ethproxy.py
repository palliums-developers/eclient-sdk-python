#!/usr/bin/python3
import operator
import sys
import json
import os
sys.path.append("..")
import log
import log.logger
import traceback
import datetime
import requests
import random
import comm
import comm.error
import comm.result
import comm.values
from comm import version
from comm.result import result, parse_except
from comm.error import error
from enum import Enum
from comm.functions import json_print
from erc20slot import (
        erc20slot,
        token_type as ERC20_NAME,
        )
from erc1155slot import (
        erc1155slot,
        idfields as fields1155,
        token_type as ERC1155_NAME,
        )
from erc721slot import (
        erc721slot,
        idfields as fields721,
        token_type as ERC721_NAME,
        )
from lbethwallet import lbethwallet
from metafiles import (
        erc1155_abi as erc1155_std_abi,
        erc721_abi as erc721_std_abi,
        #erc20_abi as erc20_std_abi,
        )

import web3
from web3 import Web3

#module name
name="ethproxy"

logger = log.logger.getLogger(name) 

contract_codes = {
        #ERC20_NAME      : {"abi":erc20_std_abi.ABI, "bytecode":erc20_std_abi.BYTECODE, "token_type": "erc20", "address": erc20_std_abi.ADDRESS},
        ERC721_NAME      : {"abi":erc721_std_abi.ABI, "bytecode":erc721_std_abi.BYTECODE, "token_type": "erc721", "address": erc721_std_abi.ADDRESS},
        ERC1155_NAME    : {"abi":erc1155_std_abi.ABI, "bytecode":erc1155_std_abi.BYTECODE, "token_type": "erc1155", "address": erc1155_std_abi.ADDRESS},
        }

class walletproxy(lbethwallet):
    @classmethod
    def load(self, filename, cache = True):
        ret = self.recover(filename, cache = cache)
        return ret

    @classmethod
    def loads(self, data, cache = True):
        ret = self.recover_from_mnemonic(data, cache = cache)
        return ret

    @classmethod
    def new_wallet(self):
        return self.new();

    def find_account_by_address_hex(self, address):
        for i in range(self.child_count):
            if self.accounts[i].address == address:
                return (i, self.accounts[i])

        return (-1, None)

    @classmethod
    def is_valid_address(self, address):
        return Web3.isAddress(address)

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError

class ethproxy():

    def clientname(self):
        return name
    
    def __init__(self, host, port, usd_chain = True, *args, **kwargs):
        self._w3 = None
        self.tokens_address = {}
        self.tokens_decimals = {}
        self.tokens = {}
        self.tokens_id = []
        self.__usd_chain_contract_info = usd_chain

        self.connect(host, port, *args, **kwargs)

    def connect(self, host, port = None, *args, **kwargs):
        url = host
        if "://" not in host:
            url = f"http://{host}"
            if port is not None:
                url += f":{port}"

        self._w3 = Web3(Web3.HTTPProvider(url))

    def __get_contract_info(self, token_id, tokentype = ERC1155_NAME):
        contract = contract_codes.get(token_id, contract_codes[tokentype])
        assert contract is not None, f"contract name({token_id}) is invalid."
        return contract

    def local_contract_info(self):
        json_print(contract_codes)

    def load_contract(self, token_id, address = None, tokentype = ERC20_NAME):
        contract = self.__get_contract_info(token_id, tokentype)
        assert contract is not None, f"not support token({token_id})"

        address = contract["address"] if not address else address

        erc_token = None
        if tokentype == ERC20_NAME:
            erc_token = erc20slot(self._w3.eth.contract(Web3.toChecksumAddress(address), abi=contract["abi"]))
            self.tokens_decimals[token_id] = pow(10, self.__get_token_decimals_with_name(erc_token, token_id))
        elif tokentype == ERC1155_NAME:
            erc_token = erc1155slot(self._w3.eth.contract(Web3.toChecksumAddress(address), abi=contract["abi"]))
            self.tokens_decimals[token_id] = 0
        elif tokentype == ERC721_NAME:
            erc_token = erc721slot(self._w3.eth.contract(Web3.toChecksumAddress(address), abi=contract["abi"]))
            self.tokens_decimals[token_id] = 0
        else:
            raise Exception("{} is invalied.".format(tokentype))

        setattr(self, token_id, erc_token)

        self.tokens_address[token_id] = address
        self.tokens[token_id] = erc_token 
        self.tokens_id.append(token_id)

    def token_address(self, token_id):
        return self.tokens_address[token_id]

    def is_connected(self):
        return self._w3.isConnected()
    
    def syncing_state(self):
        return self._w3.eth.syncing

    def get_decimals(self, token):
        return self.tokens_decimals[token]

    def allowance(self, owner, spender, token_id, **kwargs):
        return self._slot_cli(token_id).allowance(owner, spender)

    def approved(self, id, token_id, **kwargs):
        return self._slot_cli(token_id).approved(id)

    def token_manager(self, token_id, **kwargs):
        return self._slot_cli(token_id).token_manager()

    def approve(self, account, spender, value, token_id, timeout = 180, **kwargs):
        calldata = self._slot_cli(token_id).raw_approve(spender, value)
        return self.send_contract_transaction(account.address, account.key, calldata, timeout = timeout) 

    def send_token(self, account, to_address, amount, token_id, nonce = None, timeout = 180, id = None):
        if token_id.lower() == "eth":
            return self.send_eth_transaction(account.address, account.key, to_address, amount, nonce = nonce, timeout = timeout) 
        else:
            calldata = None
            if self._slot_cli(token_id).slot_name() == ERC20_NAME:
                calldata = self._slot_cli(token_id).raw_transfer(to_address, amount)
            elif self._slot_cli(token_id).slot_name() == ERC1155_NAME:
                calldata = self._slot_cli(token_id).raw_transfer_from(account.address, to_address, id, amount)
            elif self._slot_cli(token_id).slot_name() == ERC721_NAME:
                calldata = self._slot_cli(token_id).raw_transfer_from(account.address, to_address, id, 1)
            else:
                raise Exception("token_id[{}] is not [{}]".format(token_id, self.tokens_id))

            return self.send_contract_transaction(account.address, account.key, calldata, nonce = nonce, timeout = timeout) 

    def get_txn_args(self, sender, nonce = None, gas = None, gas_price = None, calldata = None):
        if not gas_price:
            gas_price = self._w3.eth.gasPrice

        if not nonce:
            nonce = self._w3.eth.getTransactionCount(Web3.toChecksumAddress(sender))

        if not gas:
            if calldata:
                gas = calldata.estimateGas({"from":sender})
            else:
                gas = self._w3.eth.estimateGas({"from":sender})

        return (nonce, gas, gas_price)

    def send_eth_transaction(self, sender, private_key, to_address, amount, nonce = None, gas = None, gas_price = None, timeout = 180):
        nonce, gas, gas_price = self.get_txn_args(sender, nonce, gas, gas_price)
        signed_txn = self._w3.eth.account.sign_transaction(dict(
            chainId = self.get_chain_id(),
            nonce = nonce,
            to = to_address,
            value = amount,
            gas = gas,
            gasPrice = gas_price
            ),
            private_key=private_key 
            )

        return self.send_transaction(signed_txn, timeout)

    def send_contract_transaction(self, sender, private_key, calldata, nonce = None, gas = None, gas_price = None, timeout = 180):
        nonce, gas, gas_price = self.get_txn_args(sender, nonce, gas, gas_price, calldata)
        raw_tran = calldata.buildTransaction({
            "chainId": self.get_chain_id(),
            "gas" : gas,
            "gasPrice": gas_price,
            "nonce" : nonce
            })

        signed_txn = self._w3.eth.account.sign_transaction(raw_tran, private_key=private_key)
        return self.send_transaction(signed_txn, timeout)

    def send_transaction(self, signed_txn, timeout):
        txhash = self._w3.eth.sendRawTransaction(signed_txn.rawTransaction)

        #wait transaction, max time is 120s
        self._w3.eth.waitForTransactionReceipt(txhash, timeout)
        return self._w3.toHex(txhash)

    def call_default(self, *args, **kwargs):
        print(f"no defined function(args = {args} kwargs = {kwargs})")

    def block_number(self):
        return self._w3.eth.blockNumber

    def get_balance(self, address, token_id, *args, **kwargs):
        if token_id == "eth":
            return self._w3.eth.getBalance(address)
        return self._slot_cli(token_id).balance_of(address, **kwargs)

    def get_balances(self, address, *args, **kwargs):
        balances = {}
        for token_id in self.tokens_id:
            id = kwargs.get("id")
            balances.update({"{}{}".format(token_id, "_" + id if id else ""): 
                self.get_balance(address, token_id, **kwargs)})

        return balances

    def get_rawtransaction(self, txhash):
        return self._w3.eth.getTransaction(txhash)

    def get_chain_id(self):
        return self._w3.eth.chainId

    def uri(self, token_id):
        return self._slot_cli(token_id).uri()

    def index_start(self, token_id, **kwargs):
        return self._slot_cli(token_id).index_start(token_id)

    def _slot_cli(self, token_id):
        if self.tokens[token_id].slot_name() in (ERC1155_NAME, ERC721_NAME):
            return self.tokens[token_id]
        else:
            raise Exception("contract is not support. token_id = {} slot_name = {}".format(token_id, self.tokens[token_id].slot_name()))


    #erc1155: data
    #erc721: tid
    def mint(self, account, token_id, to_address, id, amount = 1, data = None, timeout = 180, *args, **kwargs):
        calldata = None
        if self._slot_cli(token_id).slot_name() in (ERC1155_NAME, ERC721_NAME):
            calldata = self._slot_cli(token_id).raw_mint(to_address, id, amount, *args, **kwargs)
        else:
            raise Exception("contract is not support mint. token_id = {} slot_name = {}".format(token_id, self._slot_cli(token_id).slot_name()))

        return self.send_contract_transaction(account.address, account.key, calldata, nonce = None, timeout = timeout) 

    def pause(self, token_id):
        return self._slot_cli(token_id).pause()

    def unpause(self, token_id):
        return self._slot_cli(token_id).unpause()

    def get_token_ids_count(self, token_id):
        logger.debug("tokenid: " + token_id)
        return self._slot_cli(token_id).tokenCount()

    def get_token_id_total_amount(self, token_id, id):
        return self._slot_cli(token_id).tokenTotalAmount(id)

    def get_token_ids(self, token_id, start = 0, limit = sys.maxsize):
        ids = []
        count = self.get_token_ids_count(token_id)
        for i in range(count):
            if i >= start + limit:
                break

            if i >= start:
                id  = self._slot_cli(token_id).token_id(i)
                fields = self.get_token_fields(token_id, id)
                fields.update({"index": i, "id": id})
                ids.append(fields)

        return ids

    def get_token_fields(self, token_id, id):
        if self._slot_cli(token_id).slot_name() == ERC1155_NAME:
            ifs = fields1155(id)
            return dict(
                brand   = self._slot_cli(token_id).brand_name(ifs.brand),
                btype   = self._slot_cli(token_id).type_name(ifs.btype),
                quality = self._slot_cli(token_id).quality_name(ifs.quality),
                token_type = self._slot_cli(token_id).nfttype_name(ifs.nfttype),
                issubtoken      = ifs.issubtoken,
                quality_index   = ifs.quality_index,
                parent_token    = ifs.parent_token,
                brand_code      = ifs.brand,
                type_code       = ifs.btype,
                level_code      = ifs.quality
                )
        elif self._slot_cli(token_id).slot_name() == ERC721_NAME:
            ifs = fields721(id)
            return dict()
        else:
            return dict()


    def token_exists(self, token_id, id):
        return self._slot_cli(token_id).token_exists(id)

    def token_id(self, token, index): 
        return self._slot_cli(token).token_id(index)

    def token_type(self, token_id, id):
        return self._slot_cli(token_id).token_type(id)

    def brand_count(self, token_id):
        return self._slot_cli(token_id).brand_count()

    def brand_name(self, token_id, id):
        return self._slot_cli(token_id).brand_name(id)
        
    def brand_id(self, token_id, name):
        return self._slot_cli(token_id).brand_id(name)

    def get_type_count(self, token_id):
        return self.type_count(token_id)

    def type_count(self, token_id):
        return self._slot_cli(token_id).type_count()

    def get_type_ids(self, token_id, start = 0, limit = sys.maxsize):
        ids = []
        count = self.type_count(token_id)
        for i in range(count):
            if i >= start + limit:
                break

            if i >= start:
                id  = self._slot_cli(token_id).type_id(i)
                datas= self._slot_cli(token_id).type_datas(id)
                fields = self.get_token_fields(token_id, id)
                fields.update({
                    "index": i, 
                    "id": id, 
                    "datas": datas,
                    })
                ids.append(fields)

        return ids

    def minter_role(self, token_id):
        return self._slot_cli(token_id).minter_role()

    def pauser_role(self, token_id):
        return self._slot_cli(token_id).pauser_role()

    def admin_role(self, token_id):
        return self._slot_cli(token_id).admin_role()

    def type_name(self, token_id, id):
        return self._slot_cli(token_id).type_name(id)

    def type_id(self, token_id, key):
        return self._slot_cli(token_id).type_id(key)
        
    def type_datas(self, token_id, tid):
        return self._slot_cli(token_id).type_datas(tid)
        
    def quality_count(self, token_id):
        return self._slot_cli(token_id).quality_count()

    def quality_name(self, token_id, id):
        return self._slot_cli(token_id).quality_name(id)

    def quality_id(self, token_id, name):
        return self._slot_cli(token_id).quality_id(name)

    def nfttype_count(self, token_id):
        return self._slot_cli(token_id).nfttype_count()

    def nfttype_name(self, token_id, id):
        return self._slot_cli(token_id).nfttype_name(id)

    def nfttype_id(self, token_id, name):
        return self._slot_cli(token_id).nfttype_id(name)

    def is_blind_box(self, token_id, nfttype: int):
        return self._slot_cli(token_id).is_blind_box(nfttype)

    def is_exchange(self, token_id, nfttype : int):
        return self._slot_cli(token_id).is_exchange(nfttype)

    def grant_role(self, account, token_id, role, address, timeout = 180):
        calldata = self._slot_cli(token_id).raw_grant_role(role, address)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    def mint_brand(self, account, token_id, to_address, brand, data = None, timeout = 180):
        calldata = self._slot_cli(token_id).raw_mint_brand(to_address, brand, data)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    #1155
    def mint_type(self, account, token_id, to_address, brand, btype, data = None, timeout = 180):
        calldata = self._slot_cli(token_id).raw_mint_type(to_address, brand, btype, data)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    #721
    def append_type(self, account, token_id, id, capacity, data = None, timeout = 180):
        calldata = self._slot_cli(token_id).raw_mint_type(id, capacity, data)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    def mint_quality(self, account, token_id, to_address, brand, btype, quality, nfttype, data = None, timeout = 180):
        calldata = self._slot_cli(token_id).raw_mint_quality(to_address, brand, btype, quality, nfttype, data)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    def mint_sub_token(self, account, token_id, to_address, quality_id, amount, data = None, timeout = 180):
        calldata = self._slot_cli(token_id).raw_mint_sub_token(to_address, quality_id, amount, data)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    def exchange_blind_box(self, account, token_id, to_address, id, data = None, timeout = 180):
        calldata = self._slot_cli(token_id).raw_mint_exchange_blind_box(to_address, id, data)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 


    def append_blind_box_id(self, account, token_id, nfttype, timeout = 180):
        calldata = self._slot_cli(token_id).raw_append_blind_box_id(nfttype)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    def cancel_blind_box_id(self, account, token_id, nfttype, timeout = 180):
        calldata = self._slot_cli(token_id).raw_cancel_blind_box_id(nfttype)
        return self.send_contract_transaction(account.address, 
                account.key, 
                calldata, 
                nonce = None, 
                timeout = timeout) 

    def sha3_id(self, num = None, text=None):
        if text:
            return Web3.sha3(hexstr=(Web3.toHex(text=text))).hex()
        if num:
            return Web3.sha3(hexstr= 
                Web3.toHex(hexstr= (
                     Web3.toHex(hexstr=num)[2:]).zfill(64))
                ).hex()
            raise Exception("input num or text")

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            # Python internal stuff
            raise AttributeError
        raise Exception(f"not defined function:{name}")
        
    def __call__(self, *args, **kwargs):
        pass



def main():
    client = clientproxy.connect("")
    client.local_contract_info();
if __name__ == "__main__":
    main()
