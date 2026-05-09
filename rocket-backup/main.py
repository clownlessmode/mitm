from mitmproxy import http

import main_balance
import replace_check
import replace_details
import replace_history
import search


def request(flow: http.HTTPFlow) -> None:
    replace_check.request(flow)


def response(flow: http.HTTPFlow) -> None:
    main_balance.response(flow)
    replace_history.response(flow)
    replace_details.response(flow)
    search.response(flow)
    replace_check.response(flow)

