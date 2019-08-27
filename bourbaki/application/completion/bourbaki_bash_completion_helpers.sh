#!/usr/bin/env bash

# completions can be registered like so:

#    _complete_my_awesome_cli() {
#    _bourbaki_complete """
#    - complete pos1
#    - 2 complete pos2
#    - * complete pos3
#    --arg1 1 complete arg1
#    a
#      - 1 complete apos1
#      - 1 complete apos2
#      --aarg1 complete aarg1
#      --aarg2 2 complete aarg2
#      aa
#        --aaarg1 3 complete aaarg1
#      ab
#        - 2 complete abpos1
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
#    }
#    complete -o filenames bashdefault -F _complete_my_awesome_cli my_awesome_cli


export BOURBAKI_COMPLETION_DEBUG=false
export BOURBAKI_KEYVAL_SPLIT_CHAR="="
export BOURBAKI_UNION_SPLIT=" && "
export BOURBAKI_TUPLE_SPLIT=" ; "
BOURBAKI_COMPGEN_PYTHON_CLASSPATHS_SCRIPT="compgen_python_classpaths.py"
BASH_COMPLETION_FILEDIR="_filedir"
BASH_COMPLETION_CUR_WORD="_get_comp_words_by_ref"


_bourbaki_complete() {
    # temp vars
    #     option str  arg spec    positional     cmd name   cmd spec
    local cur_opt='' cur_spec='' cur_pos=0 ix=0 cur_cmd='' cmd_tree="$1"; shift
    local cur_token token nargs ntokens add completer positional new_command
    # the command line to complete
    local ARGS
    # should we complete command names?
    local complete_commands=false
    # should we complete --options?
    local complete_options=false
    # number of positional args in the cmd spec
    local npos="$(_n_positionals "$cmd_tree")"

    if [ $# -eq 0 ]; then
        # if no args passed, use the bash default
        ARGS=("${COMP_WORDS[@]}")
        cur_token="${COMP_WORDS[$COMP_CWORD]}"
    else
        # else treat the args as the command line to be completed
        ARGS=("$@")
        cur_token="${ARGS[-1]}"
    fi
    # total number of tokens in the command line
    ntokens="${#ARGS[@]}"

    _bourbaki_debug

    # figure out what to complete by going through the tokens
    while [ "${#ARGS[@]}" -ge 1 ]; do
        # first token
        token="${ARGS[0]}"
        _bourbaki_debug "ARGS: ${#ARGS[@]}: $(_print_args "${ARGS[@]}")" && _bourbaki_debug "TOKEN: '$token' INDEX: $ix"
        nargs=''
        positional=false
        new_command=false
        complete_commands=false
        complete_options=false

        if [ "${#ARGS[@]}" -eq 1 ] && ([ -z "$token" ] || _is_optional "$token"); then
            # only one token, which is an --option or empty; complete available options
            complete_options=true
            _bourbaki_debug "LAST TOKEN '$token' IS OPTION; COMPLETE OPTIONS"
        fi

        if _is_optional "$token" && _is_option "$cmd_tree" "$token"; then
            # if the current token is an --option for the current command, get the completion spec for this option;
            # consume the token / advance forward 1
            cur_opt="$token"
            cur_spec="$(_argspec_for_optional "$cmd_tree" "$cur_opt")"
            # skip the flag
            _bourbaki_debug "KNOWN OPTION: '$token'; SKIPPING AHEAD 1" &&
            _bourbaki_debug "NEW OPTION SPEC: $cur_spec"
            ARGS=("${ARGS[@]:1}")
            ((ix+=1))
        else
            # not an --option
            cur_opt=''
            if _positionals_are_consumed "$npos" "$cur_pos" "$token" "$cmd_tree"; then
                # if there are no positionals left to complete for, then
                _bourbaki_debug "CONSUMED POSITIONALS FOR COMMAND $cur_cmd: $cur_pos out of $npos"

                if _has_suffix "$npos" '-'; then
                    # variadic positional allows more positionals to be consumed; continue
                    cur_spec="$(_argspec_for_positional "$cmd_tree" "$((cur_pos))")"
                    positional=true
                    _bourbaki_debug "PARSE CONTINUED POSITIONALS FOR SPEC $cur_spec"
                fi

                if [ "${#ARGS[@]}" -eq 1 ]; then
                    # last token is a potential subcommand; don't parse subtree so we can use it to complete commands
                    complete_commands=true
                    _bourbaki_debug "LAST TOKEN NON-OPTION; ALLOW COMMAND COMPLETION"
                elif _is_subcommand "$cmd_tree" "$token"; then
                    # get the tree for the subcommand and start processing args for it
                    cur_cmd="$token"
                    cmd_tree="$(_subtree "$cmd_tree" "$token")"
                    npos="$(_n_positionals "$cmd_tree")"
                    cur_pos=0
                    new_command=true
                    _bourbaki_debug "FOUND COMMAND $cur_cmd; NEW TREE:" && _bourbaki_debug "$cmd_tree"
                fi
                # else an error - unknown positional; make sure no completions take effect, and skip forward 1
            elif ! _is_optional "$token"; then
                # process positional arg normally
                cur_spec="$(_argspec_for_positional "$cmd_tree" "$((cur_pos))")"
                positional=true
                _bourbaki_debug "POSITIONALS CONSUMED: $cur_pos" &&
                    _bourbaki_debug "CURRENT POSITIONAL SPEC: $cur_spec"
            fi
        fi

        if [ -z "$cur_spec" ] || "$new_command"; then
            # unknown argument; skip forward 1
            $new_command && completer="complete_command" || completer=''
            ARGS=("${ARGS[@]:1}")
            ((ix+=1))
            { $new_command && _bourbaki_debug "NEW COMMAND; CONSUMING 1 TOKEN" ||
                              _bourbaki_debug "UNKNOWN ARG; CONSUMING 1 TOKEN"; }
        else
            completer="$(_completer_from_spec "$cur_spec")"
            nargs="$(_nargs_from_spec "$cur_spec")"
            if _is_numeric "$nargs"; then
                add="$nargs"
            else
                add=$(_n_non_flags "${ARGS[@]}")
                if [ "$nargs" == '?' ]; then
                    add=$(_min 1 "$add")
                fi
            fi
            add="$(_min $((ntokens-$ix)) $add)"
            $positional && ((cur_pos+=$add))
            ((ix+=$add))
            ARGS=("${ARGS[@]:$add}")
            _bourbaki_debug "CONSUMING $add TOKENS"
        fi
        _bourbaki_debug
    done

    if $complete_options; then
        _bourbaki_complete_choices $(_flags "$cmd_tree")
    fi
    if $complete_commands; then
        _bourbaki_complete_choices $(_subcommand_names "$cmd_tree")
    fi
    if [ -n "$completer" ]; then
        # this is assumed to mutate COMPREPLY directly as the bash_completion functions do
        _eval_completer "$completer" "$subpos"
    fi

    if $BOURBAKI_COMPLETION_DEBUG; then
        _bourbaki_debug
        _bourbaki_debug "COMMAND: '$cur_cmd'"
        _bourbaki_debug "LAST OPTION: '$cur_opt' WITH ARG SPEC: $cur_spec"
        _bourbaki_debug "CONSUMED POSITIONALS: $cur_pos"
        _bourbaki_debug "COMPLETER: $completer"
        _bourbaki_debug "CURRENT TOKEN: '$cur_token'"
        _bourbaki_debug "REMAINDER: ${ARGS[@]}"
        _bourbaki_debug "COMPLETE COMMANDS? $complete_commands"
        _bourbaki_debug "COMPLETE OPTIONS? $complete_options"
        _bourbaki_debug "COMPLETIONS:"
        _bourbaki_debug
        _bourbaki_debug_completions
        _bourbaki_debug
    fi
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

_argspecs() {
    # print either
    # opt*: optional arg specs
    # pos*: positional arg specs
    # name*: names of optional args
    local check strip prefix
    case "$1" in
        opt*) check=_is_optional strip=_lstrip_chars prefix='-';;
        pos*) check=_is_positional strip=_lstrip prefix='- ';;
        name*) check=_is_optional strip=_rstrip prefix=' *';;
    esac
    local cmdtree="$2" line
    printf '%s\n' "$cmdtree" | {
    local IFS=$'\n'
    while read line; do
        [ -z "$line" ] && continue
        $check $line && $strip "$line" "$prefix"
        _has_prefix "$line" ' ' && break
    done
    }
}

_flags() {
    _argspecs names "$1"
}

_argnames() {
    local line
    _flags "$1" | {
    while read line; do
        _lstrip_chars "$line" '-'
    done
    }
}

_n_positionals() {
    local cmdtree="$1" spec nargs total=0
    _positional_argspecs "$cmdtree" | {
        while read spec; do
            nargs="$(_nargs_from_spec "$spec")"
            if _is_numeric "$nargs"; then
                ((total+="$nargs"))
            else
                case "$nargs" in
                    '*') total="$total-"; break;;
                    '+') ((total+=1)); total="$total-"; break;;
                esac
            fi
        done
        echo "$total"
    }
}

_argspec_for_optional() {
    local cmdtree="$1" arg="$(_lstrip_chars "$2" '-')" line
    _optional_argspecs "$cmdtree" | {
    while read line; do
        _has_prefix "$line" "$arg " && _lstrip "$line" "$arg " && break
    done
    }
}

_argspec_for_positional() {
    local cmdtree="$1" cur_pos="$2" spec nargs total=0
    _positional_argspecs "$cmdtree" | {
        while read spec; do
            nargs="$(_nargs_from_spec "$spec")"
            if _is_numeric "$nargs"; then
                ((total+="$nargs"))
                [ "$total" -ge "$cur_pos" ] && break
            else
                break
            fi
        done
        echo "$spec"
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
    _flags "$cmdtree" | {
        while read arg; do
            [ "$arg" == "$prefix" ] && return 0
        done
        return 1
    }
    return $?
}

_nargs_from_spec() {
    local first="$(_rstrip "$1" ' *')"
    _is_numeric "$first" && _rstrip "$first" ' *' || case "$first" in
        '*'|'+'|'?') echo "$first" ;;
    esac
}

_completer_from_spec() {
    local spec="$@"
    local nargs="$(_nargs_from_spec "$spec")"
    [ "$spec" == "$nargs" ] && echo || _lstrip "$spec" '\'"$nargs "
}

_positionals_are_consumed() {
    # are all positional arguments consumed for the command represented by cmdtree?
    local npos="$1" cur_pos="$2" token="$3" cmdtree="$4"
    if _has_suffix "$npos" '-'; then
        # variadic; only consumed if numeric part exceeded *and* token is an option or a command name
        _bourbaki_debug "check variadic positionals consumed: $cur_pos out of $npos"
        if [ "$cur_pos" -ge "$(_rstrip "$npos" -)" ]; then
            _bourbaki_debug "positionals minimum exceeded"
            if _is_optional "$token"; then
                _bourbaki_debug "'$token' is an option; positionals consumed"
                return 0
            elif _is_subcommand "$cmdtree" "$token"; then
                _bourbaki_debug "'$token' is a subcommand; positionals consumed"
                return 0
            fi
        else
            return 1
        fi
    else
        _bourbaki_debug "check fixed positionals consumed: $cur_pos out of $npos"
        [ "$cur_pos" -ge "$npos" ] && return 0 || return 1
    fi
}

_min() {
    [ $# -le 1 ] && echo "$1" && return
    local small
    [ "$1" -le "$2" ] && small="$1" || small="$2"
    shift 2
    _min "$small" "$@"
}

_n_non_flags() {
    local token i=0
    for token in "$@"; do
        _is_optional "$token" && break || ((i+=1))
    done
    echo "$i"
}

_print_args() {
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
        $((pos-=1))
    done
    completer="${completer%%\;*}"
    _bourbaki_debug "eval '$completer'"
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
        if [ "$(_lstrip_chars "$token" "$BOURBAKI_KEYVAL_SPLIT_CHAR")" == "" ] && [ ${token#} -gt 2 ]; then
            break
        fi
    done
    echo "$ix"
}

_bourbaki_complete_keyval() {
    _bourbaki_debug "COMPLETING KEY-VALUE '$@'"
    local keyval_cmd_ix=$(_get_keyval_cmd_idx "$@")
    local cur="${COMP_WORDS[$COMP_CWORD]}" last="${COMP_WORDS[$((COMP_CWORD - 1))]}"

    if [ "$cur" == "$BOURBAKI_KEYVAL_SPLIT_CHAR" ]; then
        _bourbaki_debug "COMPLETING VALUE: '$cur'"
        COMP_WORDS=("${COMP_WORDS[@]}" '')
        ((COMP_CWORD += 1))
        "${@:keyval_cmd_ix+1}"
    elif [ "$last" == "$BOURBAKI_KEYVAL_SPLIT_CHAR" ]; then
        _bourbaki_debug "COMPLETING VALUE: '$cur'"
        "${@:keyval_cmd_ix+1}"
    elif [ "$cur" != "$BOURBAKI_KEYVAL_SPLIT_CHAR" ]; then
        _bourbaki_debug "COMPLETING KEY: '$cur'"
        _complete_with_suffix "$BOURBAKI_KEYVAL_SPLIT_CHAR" "${@:1:keyval_cmd_ix-1}"
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
    local suffix="$1" compreply_len=${#COMPREPLY[@]} old_compreply=("${COMPREPLY[@]}")
    shift
    _bourbaki_debug "COMPLETE WITH SUFFIX '$suffix'"
    "$@"
    local tail="${COMPREPLY[@]:$compreply_len:${#COMPREPLY[@]}}"
    COMPREPLY=("${old_compreply[@]}" $(_compgen_with_suffix "$suffix" "${tail[@]}"))
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

_bourbaki_complete_simple_call() {
    local cur genfunc="$1" type="$2"
    $BASH_COMPLETION_CUR_WORD cur
    _bourbaki_debug "COMPLETING $type FOR '$cur'"
    COMPREPLY=("${COMPREPLY[@]}" $($genfunc "$cur"))
    _bourbaki_debug_total_completions
}

_bourbaki_complete_floats() {
    _bourbaki_complete_simple_call _compgen_floats "FLOATING POINT VALUES"
}

_bourbaki_complete_ints() {
    _bourbaki_complete_simple_call _compgen_ints "INTEGER VALUES"
}

_bourbaki_complete_bools() {
    _bourbaki_complete_simple_call _compgen_bools "BOOLEAN VALUES"
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

_bourbaki_debug_completions() {
    $BOURBAKI_COMPLETION_DEBUG && echo $'\033[31m'"${COMPREPLY[@]}"$'\033[0m' >&2
}

_bourbaki_debug() {
    $BOURBAKI_COMPLETION_DEBUG && echo $'\033[33m'"$@"$'\033[0m' >&2
}
