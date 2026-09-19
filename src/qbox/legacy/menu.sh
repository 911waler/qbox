#!/usr/bin/env bash
# Internal compatibility module; source via legacy/load.sh.

function rmainfunc (){
	echo ' 请输入功能编号。'
	local mainchoice action_ids
	action_ids="$(qbox_python -m qbox.registry --ids)" || return 1
	qe_read_choice mainchoice "$action_ids" '请输入有效的功能编号...' || return 1
	qe_dispatch_action "$mainchoice"
}

#--------------------------------- Generate ATOMIC_VELOCITIES for clusters/molecules ----------------------------------------
# Parses CIF atom symbols directly first, then falls back to Multiwfn when needed.
