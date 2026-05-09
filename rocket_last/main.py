from mitmproxy import http

import main_balance
import add_to_history
import replace_cheque
import replace_details
# import replace_check
# import replace_history
# import search


def request(flow: http.HTTPFlow) -> None:
    replace_cheque.request(flow)


def response(flow: http.HTTPFlow) -> None:
    main_balance.response(flow)
    add_to_history.response(flow)
    replace_details.response(flow)
    replace_cheque.response(flow)
    # search.response(flow)
    # replace_check.response(flow)

