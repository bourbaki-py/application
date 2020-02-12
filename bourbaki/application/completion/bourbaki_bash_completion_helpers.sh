#!/usr/bin/env bash

# completions can be registered like so:

#    MY_AWESEOME_CLI_SPEC="""
#    - complete pos1
#    - 2 complete pos2 first; complete pos2 second
#    --arg1 1(1) complete arg1
#    cmd_a
#      - 1 complete apos1
#      - 1 complete apos2
#      --aarg1 complete aarg1
#      --aarg2 2 complete aarg2 first; complete aarg2 second
#      aa
#        --aaarg1 3 complete aaarg1
#      ab
#        - 2 complete abpos1 first; complete abpos1 second
#        --abarg1 * complete abarg1
#      ac
#        --acarg1 3 complete acarg1
#        --acarg2 complete acarg2
#    c
#      ca
#        - complete capos1
#        --caarg1 1 complete caarg1
#      cb
#    d
#      - complete dpos1
#      --darg1 complete darg1
#    e
#      f
#      g
#        - complete egpos1
#        --egarg1 complete egarg1
#    """
#
#    _bourbaki_register_completion_from_spec my_awesome_cli "$MY_AWESOME_CLI_SPEC"

[ "${BOURBAKI_COMPLETION_DEBUG+x}" ] || export BOURBAKI_COMPLETION_DEBUG=false
[ "${BOURBAKI_ALWAYS_COMPLETE_COMMANDS+x}" ] || export BOURBAKI_ALWAYS_COMPLETE_COMMANDS=true
[ "${BOURBAKI_ALWAYS_COMPLETE_OPTIONS+x}" ] || export BOURBAKI_ALWAYS_COMPLETE_OPTIONS=false
export BOURBAKI_KEYVAL_SPLIT_CHAR="="
export BOURBAKI_COMPGEN_PYTHON_CLASSPATHS_SCRIPT="compgen_python_classpaths.py"
BASH_COMPLETION_FILEDIR="_filedir"
BASH_COMPLETION_CUR_WORD="_get_comp_words_by_ref"


_bourbaki_register_completion() {
    local command="$1" completer="$2"; shift 2
    local completion_opts=($@) include_defaults=true
    for opt in "${completion_opts[@]}"; do
        [ "$opt" == "-o" ] && include_defaults=false && break
    done
    $include_defaults && completion_opts=($@ -o filenames -o bashdefault)
    complete "${completion_opts[@]}" -F "$completer" "$command"
}


_bourbaki_register_completion_from_spec() {
    local command="$1" spec="$2"; shift 2
    local funcname="_complete_$command"
    local funcdef="""$funcname() {
_bourbaki_complete \"\"\"$spec\"\"\"
}
"""
    eval "$funcdef"
    _bourbaki_register_completion "$command" "$funcname" "$@"
}


_bourbaki_complete() {
    local tree="$1"; shift
    local tokens
    [ "$#" -gt 0 ] && tokens=("$@") || tokens=("${COMP_WORDS[@]:1:$COMP_CWORD}")

    _increment_optcount() {
        local opt=$1 opt_ ix=0 count break_=false
        opt_=$(_rstrip $opt $'\n')
        while [ "$ix" -lt "${#optgroups[@]}" ] && ! $break_; do
            for opt_ in $(_comma_sep_tokens "${optgroups[$ix]}"); do
                if [ "$opt_" = "$opt" ]; then
                    count="${optcounts[$ix]}"
                    optcounts[$ix]="$((count+1))"
                    break_=true
                    break
                fi
            done
            ((ix++))
        done
        $BOURBAKI_COMPLETION_DEBUG && _bourbaki_debug "new option group repetition counts: $(_optcounts)"
    }

    _remaining_opts() {
        local check
        [ "$1" == '-r' ] && check=_group_consumed || check=_group_exhausted
        local ix=0 count limit
        while [ "$ix" -lt "${#optcounts[@]}" ]; do
            count="$(_rstrip "${optcounts[$ix]}" $'\n')"
            limit="$(_rstrip "${optlimits[$ix]}" $'\n')"
            ! $check "$limit" $count && _comma_sep_tokens "${optgroups[$ix]}"
            ((ix++))
        done
    }

    _optcounts() {
        local ix=0 opt limit arr
        [ "$1" = "limit" ] && arr=("${optlimits[@]}") || arr=("${optcounts[@]}")
        while [ "$ix" -lt "${#optgroups[@]}" ]; do
            opt="${optgroups[$ix]}"
            limit="$(_lstrip "${arr[$ix]}" '\\')"
            printf ' %s' "${opt%$'\n'}=${limit%$'\n'}"
            ((ix++))
        done
    }

    local pos_specs=() opts=() optgroups=() optcounts=() optlimits=() remaining_opts=() cmd_names=() opt='' line
    while IFS= read line; do pos_specs+=("$line"); done < <(_positional_argspecs "$tree")
    opts=($(_options "$tree"))
    optgroups=($(_option_groups "$tree"))
    optcounts=($(for opt in "${optgroups[@]}"; do echo 0; done))
    optlimits=($(_optional_argspecs_nreps "$tree"))
    cmd_names=($(_subcommand_names "$tree"))

    local token ix=0 group_ix=0 group_nargs spec positionals_consumed kind
    local complete_opts=false complete_cmds=false complete_group=false advance=true last=false
    local state=READ next_state=READ

    _bourbaki_debug $'\n'"completing ${#tokens[@]} tokens: $(_print_args_array "${tokens[@]}")"
    $BOURBAKI_COMPLETION_DEBUG && _bourbaki_debug "option group repetition limits: $(_optcounts limit)"

    while [ "${#tokens[@]}" -gt 0 ]; do
        state="$next_state"
        _bourbaki_debug
        _bourbaki_debug -g "ENTER LOOP: STATE = $state"
        kind="$(_arg_kind_from_state "$state")"
        token="${tokens[0]}"
        _bourbaki_debug "TOKEN: '$token'  INDEX: $ix  ${#tokens[@]} ARGS: $(_print_args_array "${tokens[@]}")"
        [ "${#tokens[@]}" -eq 1 ] && last=true || last=false

        case $state in
            READ)
                if _is_optional "$token"; then
                    # if the token is an --option, definitely complete --options, possibly prepare to
                    # complete this current --option if present in this tree and not the last token
                    _bourbaki_debug "found option $token"
                    # advance past the --option token
                    advance=true
                    # complete --options if the last token
                    complete_opts=$last

                    # if this is a known --option, prepare to complete for it
                    if _is_option "$tree" "$token" && ! $last; then
                        # move to next token and begin completing this option, _but not_ if we're on the last token
                        _bourbaki_debug "option present in current command tree; completing"
                        opt="$token"
                        spec="$(_argspec_for_optional "$tree" "$opt")"
                        group_nargs="$(_nargs_from_spec "$spec")"
                        _bourbaki_debug "incrementing count for option $opt"
                        _increment_optcount "$opt"
                        # start at -1; since advance=true, we'll end up at 0 on increment
                        group_ix=-1
                        next_state=READ_OPT
                        # re-enter READ state if this is a simple --flag, otherwise begin reading tokens for this --option
                        [ "$group_nargs" = "0" ] && next_state=READ || next_state=READ_OPT
                    else
                        # otherwise enter the empty begin state; look for more --options, positionals, or commands;
                        # i.e, ignore the unknown --option; assume the user knows what they're up to
                        next_state=READ
                    fi
                else
                    # if we're in READ state at an empty token then we're always completing --options
                    [ -z "$token" ] && $BOURBAKI_ALWAYS_COMPLETE_OPTIONS && complete_opts=$last

                    # if all the positional args are processed,
                    if [ "${#pos_specs[@]}" -eq 0 ]; then
                        # then complete command names
                        complete_cmds=$last
                        # but if this is a known command, recurse into the subtree for this command and return
                        if _is_subcommand "$tree" "$token"; then
                            _bourbaki_debug "$token is a subcommand; recursing to subtree"
                            tree="$(_subtree "$tree" "$token")"
                            _bourbaki_complete "$tree" "${tokens[@]:1}"
                            return $?
                        fi
                        # token is not a --flag and no more positionals are left; assume the user knows what they're
                        # up to and simply move on
                        advance=true
                    else
                        # otherwise, determine the specification for the next positional arg, and enter READ_POS state
                        spec="${pos_specs[0]}"
                        pos_specs=("${pos_specs[@]:1}")
                        group_nargs="$(_nargs_from_spec "$spec")"
                        opt=''
                        # we're at first index in the argument group
                        group_ix=0
                        next_state=READ_POS
                        complete_cmds=false
                        # don't consume the token; let the READ_POS state decide what to do with it
                        advance=false
                    fi
                fi
            ;;
            # reading positional and optional args are handled identically since we advance past the --option
            # token in READ state in that case
            READ_POS|READ_OPT)
                _bourbaki_debug "processing required positions of current $kind arg $opt"
                _bourbaki_debug "group nargs = $group_nargs;  index in group = $group_ix"
                # always advance to the next token
                advance=true
                # never complete commands while starting to read an argument group; only if interrupted by an --option
                complete_cmds=false
                # complete for the group if we're on the last token
                complete_group="$last"

                # if all the required tokens are consumed for this argument group after advancing,
                if _group_consumed "$group_nargs" "$((group_ix+1))"; then
                    _bourbaki_debug "all required tokens of current $kind group are consumed"
                    if _isint "$group_nargs"; then
                        # and the nargs is a fixed int, we definitely can't read any more tokens for this arg;
                        # enter READ state on next token
                        next_state=READ
                        # can't complete --options while at the last index of this fixed-length group
                        complete_opts=false
                    else
                        # else begin reading non-required tokens for this arg
                        [ "$state" = READ_POS ] && next_state=READ_TAIL_POS || next_state=READ_TAIL_OPT
                        (_is_optional "$token" || [ -z "$token" ]) && complete_opts=$last
                    fi
                else
                    complete_opts=false
                    next_state="$state"
                fi

                # however, if we're reading a positional and we're at index 0, complete options also; ambiguous state
                if [ "$group_ix" -eq 0 ] && [ "$state" = READ_POS ]; then
                    if _is_option "$token" || [ -z "$token" ]; then
                        _bourbaki_debug "position 0 of a $kind group; completing --options"
                        complete_opts=$last
                    fi
                fi
            ;;
            # reading non-required trailing args for variadic argument groups
            READ_TAIL_POS|READ_TAIL_OPT)
                _bourbaki_debug "processing optional tail positions of variadic $kind arg $opt"
                # in this case, we always allow an --option token to interrupt the read and begin a new group
                complete_opts=$last
                # we don't allow the ambiguous case of a subcommand name interrupting a variadic argument's tokens
                complete_cmds=false
                # continue completing for this group in the case of an ambiguous '-' char - could begin an int expression;
                # but otherwise cease processing this group upon encountering an --option
                if _is_optional "$token" && [ "$token" != "-" ]; then
                    _bourbaki_debug "found --option while processing tail of variadic arg; ceasing completion"
                    complete_group=false
                    # break reading tail tokens for this arg; enter READ state
                    next_state=READ
                    # don't consume this token; let the READ state determine how to proceed
                    advance=false
                elif [ "$group_nargs" = "?" ]; then
                    _bourbaki_debug "nargs=?; breaking processing of tail positions of $kind arg $opt"
                    # if nargs = '?', this group is already exhausted;
                    # don't complete this group further
                    complete_group=false
                    # enter the READ state
                    next_state=READ
                    # and don't consume this token
                    advance=false
                else
                    # otherwise, continue completing for this group
                    complete_group=$last
                    # remain in the tail-read state if this group's nargs != ?
                    next_state="$state"
                    # and advance to the next token
                    advance=true
                fi
            ;;
        esac

        if $advance; then
            if ! $last; then
                ((ix+=1))
                ((group_ix+=1))
                _bourbaki_debug "advanced 1 token; new index is $ix; new argument index is $group_ix"
            fi
            tokens=("${tokens[@]:1}")
        fi
    done

    _bourbaki_debug -r $'\n'"EXIT LOOP: STATE = $state"

    remaining_opts=($(_remaining_opts -r))
    if ! $BOURBAKI_ALWAYS_COMPLETE_COMMANDS; then
        _bourbaki_debug "checking if options or args remain"
        # if we somehow ended up with complete_cmds=true while argument groups remained to be processed, negate this
        if [ "${#remaining_opts[@]}" -gt 0 ] || [ "${#pos_specs[@]}" -gt 0 ]; then
            _bourbaki_debug "${#remaining_opts[@]} --options remain and ${#pos_specs[@]} positionals remain; not completing subcommands"
            complete_cmds=false
        fi
    fi

    _bourbaki_debug "complete commands: $complete_cmds; complete options: $complete_opts; complete arg $complete_group"
    $BOURBAKI_COMPLETION_DEBUG && _bourbaki_debug "option group repetition limits: $(_optcounts limit)" &&\
                                  _bourbaki_debug "new option group repetition counts: $(_optcounts)" &&\
                                  _bourbaki_debug "required --options remaining: $(_print_args_array "${remaining_opts[@]}")"


    $BASH_COMPLETION_CUR_WORD cur
    _bourbaki_debug -g $'\n'"completing for token '$cur'"
    if $complete_cmds; then
        _bourbaki_debug -b $'\n'"completing commands"
        _bourbaki_complete_choices $(_subcommand_names "$tree")
    fi
    if $complete_opts; then
        _bourbaki_debug -b $'\n'"completing nonexhausted options"
        _bourbaki_complete_choices $(_remaining_opts)
    fi
    if $complete_group; then
        _bourbaki_debug -b $'\n'"completing current $kind argument"
        completer="$(_completer_from_spec "$spec")"
        _eval_completer "$completer" "$group_ix"
    fi
    _bourbaki_debug -r $'\n'"END COMPLETION"$'\n'
}

_arg_kind_from_state() {
    local state="$1"
    if _has_suffix "$state" "POS"; then
        echo positional
    elif _has_suffix "$state" "OPT"; then
        echo --option
    else
        echo ''
    fi
}

_group_consumed() {
    local nargs="$1" group_ix="$2"
    [ "$nargs" = "\*" ] && nargs="*"
    case "$nargs" in
        '?'|'*') [ "$group_ix" -ge 0 ] && return 0 || return 1 ;;
        '+') [ "$group_ix" -gt 0 ] && return 0 || return 1 ;;
        *)  if _isint "$nargs"; then
                [ "$group_ix" -ge "$((nargs))" ] && return 0 || return 1
            else
                return 0
            fi ;;
    esac
}

_group_exhausted() {
    local nargs="$1" group_ix="$2"
    [ "$nargs" = "\*" ] && nargs="*"
    case "$nargs" in
        '*'|'+') return 1 ;;
        '?') [ "$group_ix" -gt 0 ] && return 0 || return 1 ;;
        *) _isint "$nargs" && [ "$group_ix" -ge "$((nargs))" ] && return 0 || return 1 ;;
    esac
}

_subtree() {
    local cmdtree="$1" cmd="$2"
    printf '%s\n' "$cmdtree" | {
    local IFS=$'\n'
    while read line; do
        [ "${line%% *}" == "$cmd" ] && break
    done

    while read line; do
        if _has_prefix "$line" ' '; then
            printf '%s\n' "${line##  }"
        else
            break
        fi
    done
    }
}

_positional_argspecs() {
    _argspecs positional "$1"
}

_optional_argspecs() {
    _argspecs optional "$1"
}

_options() {
    _argspecs names "$1"
}

_option_groups() {
    _argspecs groups "$1"
}

_optional_argspecs_nreps() {
    local line spec
    _optional_argspecs "$1" | while read line; do
        spec="$(_lstrip "$line" "* ")"
        _nreps_from_spec "$spec"
    done
}

_argspecs() {
    # print either:
    # opt*: optional arg specs
    # pos*: positional arg specs
    # name*: names of optional args
    # group*: groups of --options
    local check strip affix iter=echo
    case "$1" in
        opt*) check=_is_optional strip=_rstrip affix='' ;;
        pos*) check=_is_positional strip=_lstrip affix='- ' ;;
        name*) check=_is_optional strip=_rstrip affix=' *' iter=_comma_sep_tokens ;;
        group*) check=_is_optional strip=_rstrip affix=' *' ;;
    esac
    local cmdtree="$2" line
    printf '%s\n' "$cmdtree" | {
    local IFS=$'\n'
    while read line; do
        [ -z "$line" ] && continue
        $check $line && $iter "$($strip "$line" "$affix")"
        _has_prefix "$line" ' ' && break
    done
    }
}

_argspec_for_optional() {
    local cmdtree="$1" flag="$2" flag_ line break_=false
    _optional_argspecs "$cmdtree" | {
    while read line && ! $break_; do
        for flag_ in $(_comma_sep_tokens "${line% *}"); do
            [ "$flag" = "$flag_" ] && break_=true && break
        done
        if $break_; then
            line="${line#* }"
            case "${line[0]}" in
                '?'|'+'|'*'|'(') _lstrip_chars "$(_lstrip "$line" "* ")" " " ;;
                *) _isint "${line[0]}" && _lstrip_chars "$(_lstrip "$line" "* ")" " " || echo "$line" ;;
            esac
            break
        fi
    done
    }
}

_subcommand_names() {
    local cmdtree="$1" line
    printf '%s\n' "$cmdtree" | {
    local IFS=$'\n'
    while read line; do
        [ -z "$line" ] && continue
        _is_positional "$line" && continue
        _is_optional "$line" && continue
        _has_prefix "$line" ' ' || _rstrip "$line" ' *'
    done
    }
}

_is_subcommand() {
    local cmdtree="$1" cmd="$2" line
    _subcommand_names "$cmdtree" | {
        while read line; do
            [ "$line" == "$cmd" ] && return 0
        done
        return 1
    }
    return $?
}

_is_option() {
    # the prefix is an option for the command represented by cmdtree
    local cmdtree="$1" prefix="$2" arg
    _options "$cmdtree" | {
        while read arg; do
            [ "$arg" == "$prefix" ] && return 0
        done
        return 1
    }
    return $?
}

_nargs_from_spec() {
    local positional=false
    if [ $# -gt 1 ]; then
        if [ "$1" = '-p' ]; then
            positional=true
        fi
        shift
    fi
    local first="$(_rstrip "$1" ' *')"  # strip everything after the first space
    local nargs="$(_rstrip "$first" '(*')"
    _is_numeric "$nargs" && echo "$nargs" ||
    case "$nargs" in
        '+'|'?') echo "$nargs" ;;
        '*') echo "\*" ;;
        '') if $positional; then
                echo 1
            else
                # assume a simple --flag if no nargs and no completer
                [ -z "$(_completer_from_spec "$1")" ] && echo 0 || echo 1
            fi
            ;;
        *) echo 1;;  # case where a completer follows directly after the --option
    esac
}

_nreps_from_spec() {
    local first="$(_rstrip "$1" ' *')"  # strip everything after the first space
    local nargs="$(_nargs_from_spec "$1")"  # find nargs
    local nreps
    case "$nargs" in
        '*'|'+'|'?'|'\*') nreps="${first:1}" ;;
        *) nreps="$(_lstrip "$first" "$nargs")" ;;
    esac
    nreps="$(_rstrip "$(_lstrip "$nreps" "(")" ")")"
    case "$nreps" in
        '+'|'?') echo "$nreps" ;;
        '*') echo "\*" ;;
        *) _is_numeric "$nreps" && echo "$nreps" || echo "\*" ;;
    esac
}

_completer_from_spec() {
    local spec="$(_lstrip_chars "$1" " ")"
    local first="${spec:0:1}"
    case "$first" in
        # we include the trailing ' ' after spec here for the case of an empty completer,
        # so as not to return the nargs char(s)
        '?'|'+'|'*'|'(') _lstrip_chars "$(_lstrip "$spec " "* ")" " " ;;
        *) _isint "$first" && _lstrip_chars "$(_lstrip "$spec " "* ")" " " || echo "$spec" ;;
    esac
}

_print_args_array() {
    local arg
    printf '%s' '( '
    for arg in "$@"; do
        printf "'%s' " "$arg"
    done
    printf '%s' ')'
}

_lstrip_chars() {
    local s="$1" c="$2"
    while [ "${s##$c}" != "$s" ]; do
        s="${s##$c}"
    done
    echo "$s"
}

_comma_sep_tokens() {
    local token line="$1"
    token="$(_rstrip "$line" ",*")"
    token="$(_rstrip "$token" " *")"
    while ! [ -z "$token" ]; do
        echo "$token"
        line="$(_lstrip "$line" "$token")"
        line="$(_lstrip "$line" ",")"
        token="$(_rstrip "$line" ",*")"
        token="$(_rstrip "$token" " *")"
    done
}

_lstrip() {
    local s="$1" prefix="$2"
    echo "${s#$prefix}"
}

_rstrip() {
    local s="$1" suffix="$2"
    echo "${s%%$suffix}"
}

_is_optional() {
    _has_prefix "$1" - && ! _is_numeric "${1:1:1}" && ! _is_positional "$1"
}

_is_positional() {
    _has_prefix "$1" '- '
}

_is_numeric() {
   local s="$1"
   local d="${s:0:1}"
   [ "$d" -lt 10 ] 2> /dev/null
}

_has_prefix() {
    local s="$1" p="$2"
    [ "${s#$p}" != "$s" ] && return 0 || return 1
}

_has_suffix() {
    local s="$1" p="$2"
    [ "${s%$p}" != "$s" ] && return 0 || return 1
}

_array_insert() {
    local name="$1" ix="$2" val="$3" insert_cmd
    insert_cmd="$name"'=("${'"$name"'[@]:0:'"$ix"'}" "'"$val"'" "${'"$name"'[@]:'"$ix"'}")'
    eval "$insert_cmd"
}

_bourbaki_no_complete() {
    return 0
}

_eval_completer() {
    local completer="$1" pos="$2"
    if ! _is_numeric "$pos"; then
        pos=0
    else
        _bourbaki_debug "eval position $pos in '$completer'"
    fi
    while [ "$pos" -gt 0 ]; do
        completer="${completer#*\;}"
        ((pos-=1))
    done
    completer="${completer%%\;*}"
    _bourbaki_debug "eval: $completer"
    eval "$completer"
}

_bourbaki_complete_union() {
    _bourbaki_debug "COMPLETIING UNION: $@"
    [ $# -eq 0 ] && return
    local comp_cmd
    for comp_cmd in "$@"; do
        $comp_cmd
    done
}

_get_keyval_cmd_idx() {
    local token ix=0 which='key'
    for token in "$@"; do
        ((ix+=1))
        if [ "$(_lstrip_chars "$token" "$BOURBAKI_KEYVAL_SPLIT_CHAR")" == "" ] && [ ${#token} -gt 2 ]; then
            break
        fi
    done
    echo "$ix"
}

_bourbaki_complete_keyval() {
    local keyval_cmd_ix="$(_get_keyval_cmd_idx "$@")"
    local cur="${COMP_WORDS[$COMP_CWORD]}" last="${COMP_WORDS[$((COMP_CWORD - 1))]}"

    if [ "$cur" == "$BOURBAKI_KEYVAL_SPLIT_CHAR" ]; then
        # just typed '=', nothing after yet
        _bourbaki_debug "FOUND '$BOURBAKI_KEYVAL_SPLIT_CHAR'; COMPLETING VALUE: ''"
        ((COMP_CWORD += 1))
        _array_insert COMP_WORDS "$COMP_CWORD" ''
        _bourbaki_debug "EVAL: ${@:$((keyval_cmd_ix+1))}"
        ${@:keyval_cmd_ix+1}
    elif [ "$last" == "$BOURBAKI_KEYVAL_SPLIT_CHAR" ]; then
        # begun typing value
        _bourbaki_debug "COMPLETING VALUE: '$cur'"
        _bourbaki_debug "EVAL: ${@:$((keyval_cmd_ix+1))}"
        ${@:$((keyval_cmd_ix+1))}
    elif [ "$cur" != "$BOURBAKI_KEYVAL_SPLIT_CHAR" ]; then
        _bourbaki_debug "COMPLETING KEY: '$cur'"
        _bourbaki_debug "EVAL: ${@:1:$((keyval_cmd_ix-1))}"
        _complete_with_suffix "$BOURBAKI_KEYVAL_SPLIT_CHAR" "${@:1:$((keyval_cmd_ix-1))}"
    fi
}

_complete_with_prefix() {
    local prefix="$1" compreply_len=${#COMPREPLY[@]} old_compreply=("${COMPREPLY[@]}")
    shift
    _bourbaki_debug "COMPLETE WITH PREFIX '$prefix'"
    "$@"
    local tail="${COMPREPLY[@]:$compreply_len:${#COMPREPLY[@]}}"
    COMPREPLY=("${old_compreply[@]}" $(_compgen_with_prefix "$prefix" "${tail[@]}"))
}

_complete_with_suffix() {
    local suffix="$1" compreply_len="${#COMPREPLY[@]}" old_compreply=("${COMPREPLY[@]}")
    shift
    _bourbaki_debug "COMPLETE WITH SUFFIX '$suffix' USING COMMAND: $@"
    "$@"
    local tail="${COMPREPLY[@]:$compreply_len}"
    COMPREPLY=("${old_compreply[@]}" $(_compgen_with_suffix "$suffix" ${tail[@]}))
    _bourbaki_debug "COMPREPLY HAS ${#COMPREPLY[@]} TOKENS"
}

_bourbaki_complete_choices() {
    _bourbaki_debug "COMPLETIING $# CHOICES: $@"
    [ $# -eq 0 ] && return
    local cur
    $BASH_COMPLETION_CUR_WORD cur
    COMPREPLY=("${COMPREPLY[@]}" $(compgen -W "$(echo $@)" -- "$cur"))
    _bourbaki_debug_total_completions
}

_bourbaki_complete_files() {
    _bourbaki_debug "COMPLETIING FILES FOR EXTENSIONS: $@"
    # the bash completion _filedir function needs $cur set globally for some reason
    $BASH_COMPLETION_CUR_WORD cur

    if [ $# -eq 0 ]; then
        $BASH_COMPLETION_FILEDIR
    else
        local ext
        for ext in "$@"; do
            $BASH_COMPLETION_FILEDIR "${ext#.}"
        done
    fi
    _bourbaki_debug_total_completions
}

_bourbaki_complete_python_classpaths() {
    local cur
    $BASH_COMPLETION_CUR_WORD cur
    _bourbaki_debug "COMPLETING PYTHON CLASSPATHS FOR '$cur'; LEGAL PREFIXES: $@"
    COMPREPLY=("${COMPREPLY[@]}" $($BOURBAKI_COMPGEN_PYTHON_CLASSPATHS_SCRIPT "$cur" "$@"))
    _bourbaki_debug_total_completions
}

_bourbaki_complete_simple_compgen_call() {
    local cur genfunc="$1" type="$2"
    $BASH_COMPLETION_CUR_WORD cur
    _bourbaki_debug "COMPLETING $type FOR '$cur'"
    COMPREPLY=("${COMPREPLY[@]}" $($genfunc "$cur"))
    _bourbaki_debug_total_completions
}

_bourbaki_complete_floats() {
    _bourbaki_complete_simple_compgen_call _compgen_floats "FLOATING POINT VALUES"
}

_bourbaki_complete_ints() {
    _bourbaki_complete_simple_compgen_call _compgen_ints "INTEGER VALUES"
}

_bourbaki_complete_bools() {
    _bourbaki_complete_simple_compgen_call _compgen_bools "BOOLEAN VALUES"
}

_isint() {
    [ "$1" -eq "$1" ] 2>/dev/null
}

_isbasicint() {
    _isint "$1" && ! _has_prefix "$1" - && ! _has_prefix "$1" + && return 0 || return 1
}

_isfloat() {
    local n l r exp tail status
    if _has_prefix "$1" '-'; then n="$(_lstrip "$1" '-')";
    elif _has_prefix "$1" '+'; then n="$(_lstrip "$1" '+')";
    else n="$1"; fi

    l="${n%%.*}"
    tail="${n#$l.}"

    if [ "$l" == "$n" ]; then
        if _isint "$1"; then  # no decimal
            return 0
        fi
        l="${tail%%e*}" r=''
        exp="${tail#$l'e'}"
    else
        r="${tail%%e*}"
        exp="${tail#$r'e'}"
    fi

    ( _isbasicint "$l" || [ -z "$l" ]) && ( _isbasicint "$r" || [ -z "$r" ]) &&
    ( [ -n "$l" ] || [ -n "$r" ] ) && status=true || status=false

    if [ "$r" == "$tail" ]; then  # no exponent
        $status && return 0 || return 1
    else
        $status && _isint "$exp" && return 0 || return 1
    fi
}

_trailing_decimals() {
    local i
    for ((i=0; i<10; i++)); do echo "$1$i"; done
}

_compgen_with_prefix() {
    local prefix="$1" s; shift
    for s in "$@"; do printf "$prefix%s\n" "$s"; done
}

_compgen_with_suffix() {
    local suffix="$1" s; shift
    for s in "$@"; do printf "%s$suffix\n" "$s"; done
}

_compgen_ints() {
    if [ -z "$1" ]; then
        echo -; echo +
    elif ! [ "$1" == '-' ] && ! [ "$1" == '+' ] && ! _isint "$1"; then
        return
    fi
    _trailing_decimals "$1"
}

_compgen_bools() {
    echo 0; echo 1; echo True; echo False
}

_compgen_floats() {
    if [ -z "$1" ]; then
       _compgen_ints "$1"
       echo '.'; echo '-'; echo '+'
    elif [ "$1" == '-' ] || [ "$1" == '+' ]; then
       _compgen_ints "$1"
       echo '.'
    elif [ "$1" == '.' ] || [ "$1" == '-.' ] || [ "$1" == '+.' ]; then
       _trailing_decimals "$1"
    elif [ "${1%e}" != "$1" ] && _isfloat "${1%e}"; then
       _trailing_decimals "$1"
       echo '-'
    elif  [ "${1%e-}" != "$1" ] && _isfloat "${1%%e-}"; then
       _trailing_decimals "$1"
    elif _isfloat "$1"; then
       _trailing_decimals "$1"
       [ "${1%%e*}" ==  "$1" ] && echo 'e'
    fi
}

_bourbaki_debug_total_completions() {
    $BOURBAKI_COMPLETION_DEBUG && _bourbaki_debug "TOTAL COMPLETIONS: ${#COMPREPLY[@]}"
}

_bourbaki_debug() {
    local color=''
    case "$1" in
        -r) color=31; shift ;;
        -g) color=32; shift ;;
        -b) color=34; shift ;;
        *) color=33 ;;
    esac
    $BOURBAKI_COMPLETION_DEBUG && echo $'\033['"$color"'m'"$@"$'\033[0m' >&2
}
