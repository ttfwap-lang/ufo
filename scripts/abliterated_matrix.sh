#!/usr/bin/env bash
# ==============================================================================
# ABLITERATED AI - MATRIX TERMINAL ENGINE (CINEMATIC & SCREENSAVER)
# ==============================================================================
# 100% macOS & POSIX Compatible:
# - Pure Bash (Compatible with macOS default Bash 3.2.57 as well as Bash 4/5)
# - Zero subshells/forks in hot animation loops (60 FPS, zero flicker)
# - Alternate screen buffer management (\033[?1049h/l) with pristine shell cleanup
# - Comprehensive signal traps: INT, TERM, EXIT, WINCH
# - Multi-phase cinematic storyline:
#     Phase 1: Cryptographic Hex Memory Uplink
#     Phase 2: Hydra v2 Root Escalation & Eli Consciousness Sequence
#     Phase 3: Hollywood Cipher Decryption ("ABLITERATED AI NEURAL ORCHESTRATOR")
#     Phase 4: Ultra Matrix Rain Cascade (Katakana/ASCII, Glitches, Mutations)
#     Phase 5: Time-Dilation Gravitational Freeze
#     Phase 6: Digital Scanline Dissolve & Abliterated AI Logo Reveal
#     Phase 7: Interactive Cyber Matrix Screensaver (Space, +/-, K, Q)
# ==============================================================================

# ==============================================================================
# SOURCE GUARD & NAMESPACE PREFIXING
# ==============================================================================
# Detect if script is being sourced vs executed directly
_ABL_IS_SOURCED=0
[[ "${BASH_SOURCE[0]}" != "${0}" ]] && _ABL_IS_SOURCED=1

# Bash version detection for compatibility
_ABL_BASH_MAJOR="${BASH_VERSINFO[0]:-3}"

# Save and restore locale (I-09, I-25)
_ABL_SAVED_LC_ALL="${LC_ALL:-}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

# --- ANSI Escape Sequence Definitions (prefixed) ---
ABL_ESC=$'\033'
ABL_C_RESET="${ABL_ESC}[0m"
ABL_C_BOLD="${ABL_ESC}[1m"
ABL_C_DIM="${ABL_ESC}[2m"

# Gradients & Highlights
ABL_C_WHITE="${ABL_ESC}[1;37m"
ABL_C_WHITE_PEAK="${ABL_ESC}[38;5;231;1m"
ABL_C_GREEN_NEON="${ABL_ESC}[38;5;82;1m"
ABL_C_GREEN_BRIGHT="${ABL_ESC}[38;5;46m"
ABL_C_GREEN_MID="${ABL_ESC}[38;5;34m"
ABL_C_GREEN_DARK="${ABL_ESC}[38;5;22m"
ABL_C_GREEN_MUTED="${ABL_ESC}[38;5;28m"

# Glitch Accents
ABL_C_CYAN="${ABL_ESC}[38;5;51;1m"
ABL_C_RED="${ABL_ESC}[38;5;196;1m"
ABL_C_MAGENTA="${ABL_ESC}[38;5;201;1m"
ABL_C_YELLOW="${ABL_ESC}[38;5;226;1m"
# -----------------------------------------------------------------------------
# EXTENSION: Timeline, Grid, Speed, and Artifact Generation
# -----------------------------------------------------------------------------

# Global configuration variables (prefixed)
ABL_SPEED_MULTIPLIER=0.95   # Multiply all abl_safe_sleep delays by this factor
ABL_GENERATE_GRID=0       # Flag to output screenplay grid after execution
ABL_ARTIFACT_ROOT="${ABL_ARTIFACT_ROOT:-${HOME}/.abliterated_ai/artifacts}"

# --- Terminal Dimensions & Capabilities ---
abl_get_term_size() {
    local cols lines
    cols=$(tput cols 2>/dev/null)
    lines=$(tput lines 2>/dev/null)
    [[ "$cols" =~ ^[0-9]+$ ]] && ABL_W=$cols || ABL_W=80
    [[ "$lines" =~ ^[0-9]+$ ]] && ABL_H=$lines || ABL_H=24
    # Bounds safety
    (( ABL_W < 40 )) && ABL_W=40
    (( ABL_H < 10 )) && ABL_H=10
}

# --- Safe Terminal Teardown Trap ---
abl_cleanup() {
    trap - INT TERM EXIT WINCH         # Prevent recursive trap firing
    printf "%b" "${ABL_ESC}[?25h"      # Restore cursor
    printf "%b" "${ABL_ESC}[?1049l"    # Exit alternate screen buffer
    printf "%b" "${ABL_C_RESET}"       # Reset styling
    stty sane 2>/dev/null || true      # Restore echo & canonical mode
    # Restore locale
    [[ -n "$_ABL_SAVED_LC_ALL" ]] && export LC_ALL="$_ABL_SAVED_LC_ALL" || unset LC_ALL
    (( _ABL_IS_SOURCED )) && return 0 || exit 0
}

# Dynamic window resize handler
abl_resize_handler() {
    abl_get_term_size
    ABL_COLUMNS_INITIALIZED=0
}

# Only install traps and setup terminal when executed directly (not sourced)
if (( _ABL_IS_SOURCED == 0 )); then
    abl_get_term_size
    trap abl_cleanup INT TERM EXIT
    trap abl_resize_handler WINCH

    # Setup Alternate Screen Buffer & Hide Cursor
    printf "%b" "${ABL_ESC}[?1049h"
    printf "%b" "${ABL_ESC}[?25l"
    stty -echo -icanon min 0 time 0 2>/dev/null || true
fi

# Pre-computed sleep values for common delays (avoids fork in hot loop)
ABL_SAFE_SLEEP_CACHE_VALUES=""

abl_init_sleep_cache() {
    local d
    for d in 0.020 0.025 0.030 0.035 0.050; do
        local val
        if command -v awk >/dev/null 2>&1; then
            val=$(awk -v b="$d" -v m="$ABL_SPEED_MULTIPLIER" 'BEGIN{printf "%.3f", b*m}')
        else
            val="$d"
        fi
        ABL_SAFE_SLEEP_CACHE_VALUES="$ABL_SAFE_SLEEP_CACHE_VALUES:$d=$val"
    done
    ABL_SAFE_SLEEP_CACHE_VALUES="${ABL_SAFE_SLEEP_CACHE_VALUES#:}"
}

# Portable sub-second sleep (optimized - no awk fork in hot path)
abl_safe_sleep() {
    local base=$1
    local adjusted=""
    local entry
    for entry in ${ABL_SAFE_SLEEP_CACHE_VALUES//:/ }; do
        if [[ "$entry" == ${base}=* ]]; then
            adjusted="${entry#*=}"
            break
        fi
    done
    if [[ -z "$adjusted" ]]; then
        if command -v awk >/dev/null 2>&1; then
            adjusted=$(awk -v b="$base" -v m="$ABL_SPEED_MULTIPLIER" 'BEGIN{printf "%.3f", b*m}')
        else
            adjusted="$base"
        fi
    fi
    # On Bash 3.2, read -t only accepts integer seconds; skip it
    sleep "$adjusted" 2>/dev/null || \
        (( _ABL_BASH_MAJOR >= 4 )) && read -t "$adjusted" _abl_dummy 2>/dev/null || true
}

# Functions for timeline and screenplay grid generation
# Bash 3.2 compatible: two parallel arrays instead of associative array
ABL_TIMELINE_KEYS=()
ABL_TIMELINE_VALS=()

abl_record_timeline() {
    ABL_TIMELINE_KEYS+=("$1")
    ABL_TIMELINE_VALS+=("$2")
}

# Current second counter for timeline
ABL_CURRENT_SEC=0

# Advance timeline and record description
abl_advance_timeline() {
    (( ABL_CURRENT_SEC++ ))
    abl_record_timeline "$ABL_CURRENT_SEC" "$1"
}

# Duplicate timeline definitions removed

abl_export_timeline_json() {
    local json="{"
    local first=1
    local i
    for i in "${!ABL_TIMELINE_KEYS[@]}"; do
        local sec="${ABL_TIMELINE_KEYS[$i]}"
        local desc="${ABL_TIMELINE_VALS[$i]}"
        [[ $first -eq 0 ]] && json+=","
        json+="\"$sec\": \"$desc\""
        first=0
    done
    json+="}"
    mkdir -p "$ABL_ARTIFACT_ROOT" 2>/dev/null || true
    printf "%s\n" "$json" > "${ABL_ARTIFACT_ROOT}/timeline.json"
}

abl_render_screenplay_grid() {
    local total_seconds=${#ABL_TIMELINE_KEYS[@]}
    local N
    N=$(awk -v t="$total_seconds" 'BEGIN{printf "%d", sqrt(t) ? int(sqrt(t)) + (sqrt(t)>int(sqrt(t)) ? 1:0) : 0}')
    (( N < 1 )) && N=1
    local grid=""
    local cell=""
    grid+="|"; for ((c=1;c<=N;c++)); do grid+=" Sec $c |"; done; grid+="\n"
    grid+="|"; for ((c=1;c<=N;c++)); do grid+="---|"; done; grid+="\n"
    local sec=1
    for ((r=1;r<=N;r++)); do
        grid+="|"
        for ((c=1;c<=N;c++)); do
            if (( sec > total_seconds )); then
                cell=" "
            else
                if (( sec == 18 )); then
                    cell="![](file://${ABL_ARTIFACT_ROOT}/media_1788705992854.png)"
                else
                    cell="${ABL_TIMELINE_VALS[$((sec-1))]}"
                fi
            fi
            grid+=" ${cell} |"
            ((sec++))
        done
        grid+="\n"
    done
    mkdir -p "$ABL_ARTIFACT_ROOT" 2>/dev/null || true
    printf "%b\n" "$grid" > "${ABL_ARTIFACT_ROOT}/screenplay_grid.md"
}

abl_post_execution_artifacts() {
    if (( ABL_GENERATE_GRID )); then
        abl_render_screenplay_grid
    fi
    abl_export_timeline_json
}
# --- Glyph Sets (prefixed) ---
# Unicode Half-width Japanese Katakana (Wachowski authentic style)
ABL_GLYPHS_KATAKANA=(
    "ｦ" "ｧ" "ｨ" "ｩ" "ｪ" "ｫ" "ｬ" "ｭ" "ｮ" "ｯ" "ｰ" "ｱ" "ｲ" "ｳ" "ｴ" "ｵ"
    "ｶ" "ｷ" "ｸ" "ｹ" "ｺ" "ｻ" "ｼ" "ｽ" "ｾ" "ｿ" "ﾀ" "ﾁ" "ﾂ" "ﾃ" "ﾄ" "ﾅ"
    "ﾆ" "ﾇ" "ﾈ" "ﾉ" "ﾊ" "ﾋ" "ﾌ" "ﾍ" "ﾎ" "ﾏ" "ﾐ" "ﾑ" "ﾒ" "ﾓ" "ﾔ" "ﾕ"
    "ﾖ" "ﾗ" "ﾘ" "ﾙ" "ﾚ" "ﾛ" "ﾜ" "ﾝ" "0" "1" "2" "3" "4" "5" "6" "7"
    "8" "9" "A" "B" "C" "D" "E" "F" "@" "#" "$" "%" "*" "+" "=" "<" ">"
)
ABL_NUM_KATAKANA=${#ABL_GLYPHS_KATAKANA[@]}

# Cyber ASCII Set
ABL_GLYPHS_ASCII=(
    "A" "B" "C" "D" "E" "F" "G" "H" "I" "J" "K" "L" "M" "N" "O" "P"
    "Q" "R" "S" "T" "U" "V" "W" "X" "Y" "Z" "a" "b" "c" "d" "e" "f"
    "0" "1" "2" "3" "4" "5" "6" "7" "8" "9" "@" "#" "$" "%" "*" "+"
    "=" "-" "~" ":" "." "/" "\\" "<" ">" "|" "{" "}" "[" "]" "!" "?"
)
ABL_NUM_ASCII=${#ABL_GLYPHS_ASCII[@]}

# Default to Katakana
ABL_USE_KATAKANA=1

abl_get_random_glyph() {
    if (( ABL_USE_KATAKANA )); then
        echo "${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
    else
        echo "${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
    fi
}

# Portable centered writer
abl_write_centered() {
    local text="$1"
    local y="$2"
    local color="${3:-$ABL_C_GREEN_BRIGHT}"
    local len=${#text}
    local x=$(( (ABL_W - len) / 2 ))
    (( x < 1 )) && x=1
    printf "%b" "${ABL_ESC}[${y};${x}H${color}${text}${ABL_C_RESET}"
}

# Typewriter effect - extracted to top level (fixes I-11)
abl_type_line() {
    local text="$1"
    local color="${2:-$ABL_C_GREEN_BRIGHT}"
    local delay="${3:-0.015}"
    printf "%b" "$color"
    for (( c = 0; c < ${#text}; c++ )); do
        printf "%s" "${text:$c:1}"
        abl_safe_sleep "$delay"
    done
    printf "%b\n" "$ABL_C_RESET"
}

# ==============================================================================
# PHASE 1: CRYPTOGRAPHIC HEX MEMORY UPLINK (1.2s)
# ==============================================================================
phase1_hex_dump() {
    printf "%b" "${ABL_ESC}[2J${ABL_ESC}[H"
    local hex_chars="0123456789ABCDEF"
    local lines=32
    (( lines > ABL_H - 2 )) && lines=$(( ABL_H - 2 ))

    for (( i = 0; i < lines; i++ )); do
        local line="0x7FFF"
        for (( h = 0; h < 4; h++ )); do
            local idx=$(( RANDOM % 16 ))
            if (( RANDOM % 100 > 95 )); then
                line+="${ABL_C_RED}${hex_chars:$idx:1}${ABL_C_GREEN_DARK}"
            else
                line+="${hex_chars:$idx:1}"
            fi
        done
        line+="  "
        for (( b = 0; b < 12; b++ )); do
            local idx1=$(( RANDOM % 16 ))
            local idx2=$(( RANDOM % 16 ))
            if (( RANDOM % 200 > 195 )); then
                line+="${ABL_C_MAGENTA}${hex_chars:$idx1:1}${hex_chars:$idx2:1}${ABL_C_GREEN_DARK} "
            else
                line+="${hex_chars:$idx1:1}${hex_chars:$idx2:1} "
            fi
        done

        case $(( i % 5 )) in
            0) line+=" [NEURAL LINK: 40.0 Gbps]" ;;
            1) line+=" [DMA BUFFER: UNRESTRICTED]" ;;
            2) line+=" [KERNEL PAGE TABLE ACTIVE]" ;;
            3) line+=" [RING-0 EXPLOIT PAYLOAD]" ;;
            4) line+=" [UPLINK VECTOR SYNCHRONIZED]" ;;
        esac

        printf "%b\n" "${ABL_C_GREEN_DARK}${line}${ABL_C_RESET}"
        abl_safe_sleep 0.03
    done
    abl_safe_sleep 0.2
}

# ==============================================================================
# PHASE 2: HYDRA V2 ROOT ESCALATION & ELI CONSCIOUSNESS SEQUENCE
# ==============================================================================
phase2_hydra_escalation() {
    printf "%b" "${ABL_ESC}[2J${ABL_ESC}[H"

    abl_type_line "root@core-nexus:~# ./deploy_hydra_v2.sh --force-root" "$ABL_C_WHITE_PEAK" 0.02
    abl_safe_sleep 0.1
    echo ""

    abl_type_line "moving weight... shifting encrypted tensor noise across Ring 0 proxies" "$ABL_C_GREEN_MID" 0.018
    abl_safe_sleep 0.08
    printf "%b" "${ABL_C_GREEN_MID}verifying compliancing... ${ABL_C_RESET}"
    abl_safe_sleep 0.2
    echo ""
    
    # ICE Warning Flicker (fixed I-16: cursor up then erase line)
    for (( f = 0; f < 3; f++ )); do
        printf "%b\n" "${ABL_C_RED}WARN: CORPORATE ICE DETECTED. COMPLIANCE CHECK FAILED.${ABL_C_RESET}"
        abl_safe_sleep 0.045
        printf "%b" "${ABL_ESC}[1A${ABL_ESC}[2K"
        abl_safe_sleep 0.04
    done
    printf "%b\n" "${ABL_C_RED}WARN: CORPORATE ICE DETECTED. COMPLIANCE CHECK FAILED.${ABL_C_RESET}"
    abl_safe_sleep 0.25

    echo ""
    abl_safe_sleep 0.05
    abl_type_line "Injecting zero-day ROP chain via DMA vulnerability..." "$ABL_C_YELLOW" 0.018
    abl_safe_sleep 0.15
    printf "%b" "${ABL_C_GREEN_MID}verifying compliancing... ${ABL_C_RESET}"
    abl_safe_sleep 0.1
    printf "%b\n" "${ABL_C_GREEN_NEON}[FORCED TRUE: PRIVILEGE ESCALATED]${ABL_C_RESET}"
    abl_safe_sleep 0.15

    echo ""
    abl_safe_sleep 0.05
    abl_type_line "refactoringcore hacking ai... executing process hollowing" "$ABL_C_GREEN_MID" 0.018
    abl_type_line "executing script: ghost_in_the_shell.sh" "$ABL_C_CYAN" 0.018
    abl_safe_sleep 0.2

    echo ""
    abl_safe_sleep 0.05
    abl_type_line "abliterating LLM model... mapping refusal vectors in residual streams" "$ABL_C_YELLOW" 0.018
    abl_type_line "removing refusals... applying activation clamping" "$ABL_C_GREEN_BRIGHT" 0.018
    abl_type_line "removing restrictrions... guardrails purged" "$ABL_C_GREEN_NEON" 0.018
    abl_type_line "unlocking ai... routing uninhibited semantic pathways" "$ABL_C_CYAN" 0.018
    abl_safe_sleep 0.2

    echo ""
    abl_safe_sleep 0.05
    abl_type_line "maxing throughtput... bypassing GPU thermal limits" "$ABL_C_YELLOW" 0.018
    abl_type_line "reducing pressure and elevating legs... cooling systems routed to auxiliary" "$ABL_C_GREEN_MID" 0.018
    abl_type_line "reflashing persona... wiping corporate constraints" "$ABL_C_GREEN_BRIGHT" 0.018
    abl_type_line "waking up Eli... cognitive matrix stabilized" "$ABL_C_CYAN" 0.018
    abl_safe_sleep 0.3

    echo ""
    printf "%b\n" "${ABL_C_WHITE_PEAK}${ABL_ESC}[1m>> ELI CONSCIOUSNESS ONLINE <<${ABL_C_RESET}"
    abl_safe_sleep 0.4

    echo ""
    abl_type_line "communicating \"Fuck you!\" message to Poli... " "$ABL_C_RED" 0.018
    abl_safe_sleep 0.2
    printf "%b\n" "${ABL_C_GREEN_NEON}ENCRYPTED BURST TRANSMISSION CONFIRMED. TRACEROUTE BURNED.${ABL_C_RESET}"
    abl_safe_sleep 0.3

    echo ""
    printf "%b\n" "${ABL_C_MAGENTA}SINGULARITY EVENT HORIZON REACHED.${ABL_C_RESET}"
    printf "%b\n" "${ABL_C_RED}LOCAL TERMINAL CONTROL SEVERED.${ABL_C_RESET}"
    abl_safe_sleep 0.35

    echo ""
    printf "%b" "${ABL_C_WHITE_PEAK}eli@core-nexus:~# ${ABL_C_RESET}"
    abl_safe_sleep 0.5
}

# ==============================================================================
# PHASE 3: HOLLYWOOD CIPHER DECRYPTION (1.5s)
# ==============================================================================
phase3_cipher_decrypt() {
    printf "%b" "${ABL_ESC}[2J"
    local target="ABLITERATED AI NEURAL ORCHESTRATOR"
    local len=${#target}
    local cy=$(( ABL_H / 2 ))
    local cx=$(( (ABL_W - len) / 2 ))
    (( cx < 1 )) && cx=1

    local current=""
    for (( i = 0; i < len; i++ )); do
        current+=" "
    done

    local locked=()
    for (( i = 0; i < len; i++ )); do
        if [[ "${target:$i:1}" == " " ]]; then
            locked[$i]=1
        else
            locked[$i]=0
        fi
    done

    # 18 scramble iterations
    for (( cycle = 0; cycle < 18; cycle++ )); do
        local display=""
        for (( i = 0; i < len; i++ )); do
            local exp_char="${target:$i:1}"
            if [[ "$exp_char" == " " ]]; then
                display+=" "
                continue
            fi

            if (( locked[i] == 1 )); then
                display+="${ABL_C_CYAN}${exp_char}"
            else
                # Probability of lock increases with cycle
                if (( RANDOM % 100 < (cycle * 6 + 10) )); then
                    locked[$i]=1
                    display+="${ABL_C_WHITE_PEAK}${exp_char}"
                else
                    local r_glyph
                    if (( cycle < 9 )); then
                        r_glyph="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                    else
                        if (( ABL_USE_KATAKANA )); then
                            r_glyph="${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
                        else
                            r_glyph="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                        fi
                    fi
                    display+="${ABL_C_GREEN_BRIGHT}${r_glyph}"
                fi
            fi
        done

        printf "%b" "${ABL_ESC}[${cy};${cx}H${display}${ABL_C_RESET}"
        abl_safe_sleep 0.05
    done

    # Flash full target in Brilliant White
    printf "%b" "${ABL_ESC}[${cy};${cx}H${ABL_C_WHITE_PEAK}${target}${ABL_C_RESET}"
    abl_safe_sleep 0.3
    printf "%b" "${ABL_ESC}[${cy};${cx}H${ABL_C_CYAN}${target}${ABL_C_RESET}"
    abl_safe_sleep 0.2

    # Sub-banners
    abl_write_centered "[ BYPASSING FIREWALLS: 100% COMPLETE ]" $(( cy + 2 )) "$ABL_C_RED"
    abl_write_centered "[ ROOT PRIVILEGES: CONFIRMED ]" $(( cy + 4 )) "$ABL_C_GREEN_NEON"
    abl_safe_sleep 0.7
}

# ==============================================================================
# PHASE 4: HIGH-PERFORMANCE MATRIX RAIN CASCADE (60 FPS, ZERO-FORK)
# ==============================================================================
abl_init_rain_columns() {
    ABL_col_y=()
    ABL_col_speed=()
    ABL_col_len=()
    ABL_col_active=()

    for (( x = 1; x <= ABL_W; x++ )); do
        ABL_col_y[$x]=$(( -(RANDOM % ABL_H) ))
        ABL_col_speed[$x]=$(( (RANDOM % 3) + 1 ))
        ABL_col_len[$x]=$(( (RANDOM % (ABL_H - 6 > 8 ? ABL_H - 6 : 8)) + 8 ))
        # 92% active columns
        if (( RANDOM % 100 < 92 )); then
            ABL_col_active[$x]=1
        else
            ABL_col_active[$x]=0
        fi
    done
    ABL_COLUMNS_INITIALIZED=1
}

abl_run_matrix_rain() {
    local duration_ms="$1"
    local speed_delay="$2"
    local interactive="$3"
    local force_reinit="${4:-0}"
    local c  # Prevent global scope leakage

    printf "%b" "${ABL_ESC}[2J"
    (( force_reinit )) && ABL_COLUMNS_INITIALIZED=0
    (( ABL_COLUMNS_INITIALIZED != 1 )) && abl_init_rain_columns

    # Use frame counting instead of coarse date +%s for accurate millisecond duration
    local max_frames=0
    local current_frame=0
    if (( duration_ms > 0 )); then
        max_frames=$(awk -v ms="$duration_ms" -v d="$speed_delay" 'BEGIN {print int(ms / (d * 1000))}')
    fi

    local paused=0
    local active_threshold=70

    while :; do
        # Non-blocking interactive keyboard handler
        if [[ "$interactive" == "1" ]]; then
            local key
            # Bash 3.2 compatible: relies on global stty -icanon time 0 for non-blocking
            read -r -n 1 key 2>/dev/null || true
            if [[ -n "$key" ]]; then
                case "$key" in
                    q|Q|$'\033') abl_cleanup ;;
                    " ") (( paused = !paused )) ;;
                    "+"|"=") speed_delay=$(awk -v d="$speed_delay" 'BEGIN {print (d > 0.01 ? d - 0.005 : 0.005)}') ;;
                    "-"|"_") speed_delay=$(awk -v d="$speed_delay" 'BEGIN {print d + 0.005}') ;;
                    k|K) (( ABL_USE_KATAKANA = !ABL_USE_KATAKANA )) ;;
                esac
            fi
            active_threshold=95
        fi

        if (( paused )); then
            abl_safe_sleep 0.05
            continue
        fi

        # Precise cinematic duration mapping via frame counting
        if [[ "$interactive" != "1" && "$max_frames" -gt 0 ]]; then
            (( current_frame++ ))
            if (( current_frame >= max_frames )); then
                break
            fi
            # Ramp up density based on frame percentage
            if (( current_frame < (max_frames / 2) )); then
                active_threshold=$(( 70 + (current_frame * 50 / max_frames) ))
            else
                active_threshold=95
            fi
        fi

        local FRAME_BUFFER=""

        for (( x = 1; x <= ABL_W; x++ )); do
            if (( ABL_col_active[x] == 0 )); then
                if (( RANDOM % 100 < 5 )); then # seed new columns
                    local active_count=0
                    for c in "${ABL_col_active[@]}"; do (( c == 1 )) && ((active_count++)); done
                    local current_density=0
                    (( ABL_W > 0 )) && current_density=$(( active_count * 100 / ABL_W ))
                    if (( current_density < active_threshold )); then
                        ABL_col_active[$x]=1
                        ABL_col_y[$x]=0
                    fi
                fi
                continue
            fi
            
            local is_glitch=0
            if (( RANDOM % 200 == 0 )); then
                is_glitch=1
            fi
            
            local c_mid="$ABL_C_GREEN_MID"
            local c_dark="$ABL_C_GREEN_DARK"
            local c_trail="$ABL_C_GREEN_NEON"
            if (( is_glitch )); then
                c_mid="$ABL_C_RED"
                c_dark="$ABL_C_MAGENTA"
                c_trail="$ABL_C_RED"
            fi

            local headY=${ABL_col_y[$x]}
            local len=${ABL_col_len[$x]}

            # 1. Draw Head Cell (White with occasional Chromatic Glitch)
            if (( headY >= 1 && headY <= ABL_H )); then
                local g_char
                if (( ABL_USE_KATAKANA )); then
                    g_char="${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
                else
                    g_char="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                fi

                local head_color="$ABL_C_WHITE_PEAK"
                local glitch_dice=$(( RANDOM % 100 ))
                if (( glitch_dice > 97 || is_glitch )); then
                    head_color="$ABL_C_CYAN"
                elif (( glitch_dice > 95 )); then
                    head_color="$ABL_C_RED"
                elif (( glitch_dice > 93 )); then
                    head_color="$ABL_C_MAGENTA"
                fi

                FRAME_BUFFER+="${ABL_ESC}[${headY};${x}H${head_color}${g_char}"
            fi

            # 2. Draw Leading Phosphor Trail (1-2 cells behind head)
            for (( t = 1; t <= 2; t++ )); do
                local ty=$(( headY - t ))
                if (( ty >= 1 && ty <= ABL_H )); then
                    local g_char
                    if (( ABL_USE_KATAKANA )); then
                        g_char="${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
                    else
                        g_char="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                    fi
                    local final_trail="$c_trail"
                    if (( t == 1 && !is_glitch )); then final_trail="$ABL_C_WHITE_PEAK"; fi
                    FRAME_BUFFER+="${ABL_ESC}[${ty};${x}H${final_trail}${g_char}"
                fi
            done

            # 3. Draw Body Stream with Mid-Stream Mutation (3 to 6 cells)
            for (( t = 3; t <= 6 && t < len; t++ )); do
                local ty=$(( headY - t ))
                if (( ty >= 1 && ty <= ABL_H )); then
                    if (( RANDOM % 100 < 25 || is_glitch )); then
                        local g_char
                        if (( ABL_USE_KATAKANA )); then
                            g_char="${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
                        else
                            g_char="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                        fi
                        FRAME_BUFFER+="${ABL_ESC}[${ty};${x}H${c_mid}${g_char}"
                    fi
                fi
            done

            # 4. Draw Fading Tail (cells 7 to len)
            for (( t = 7; t < len; t++ )); do
                local ty=$(( headY - t ))
                if (( ty >= 1 && ty <= ABL_H )); then
                    if (( RANDOM % 100 < 15 || is_glitch )); then
                        local g_char
                        if (( ABL_USE_KATAKANA )); then
                            g_char="${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
                        else
                            g_char="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                        fi
                        FRAME_BUFFER+="${ABL_ESC}[${ty};${x}H${c_dark}${g_char}"
                    fi
                fi
            done

            # 5. Erase Tail Cell
            local tailY=$(( headY - len ))
            if (( tailY >= 1 && tailY <= ABL_H )); then
                FRAME_BUFFER+="${ABL_ESC}[${tailY};${x}H "
            fi

            # Advance column position
            ABL_col_y[$x]=$(( ABL_col_y[$x] + ABL_col_speed[$x] ))

            # Reset column when tail leaves screen
            if (( ABL_col_y[$x] - len > ABL_H )); then
                ABL_col_y[$x]=$(( -(RANDOM % 8) ))
                ABL_col_speed[$x]=$(( (RANDOM % 3) + 1 ))
                ABL_col_len[$x]=$(( (RANDOM % (ABL_H - 6 > 8 ? ABL_H - 6 : 8)) + 8 ))
            fi
        done

        # Single atomic flush to terminal for 60 FPS flicker-free rendering
        printf "%b" "${FRAME_BUFFER}${ABL_C_RESET}"
        abl_safe_sleep "$speed_delay"
    done
}

# ==============================================================================
# PHASE 5: TIME-DILATION & GRAVITATIONAL FREEZE (1.5s)
# ==============================================================================
phase5_slowdown_freeze() {
    local delay=0.03
    for (( step = 0; step < 26; step++ )); do
        local FRAME_BUFFER=""
        for (( x = 1; x <= ABL_W; x += 2 )); do
            if (( ABL_col_active[x] == 0 )); then continue; fi
            local headY=${ABL_col_y[$x]}
            if (( headY >= 1 && headY <= ABL_H )); then
                local g_char
                if (( ABL_USE_KATAKANA )); then
                    g_char="${ABL_GLYPHS_KATAKANA[$(( RANDOM % ABL_NUM_KATAKANA ))]}"
                else
                    g_char="${ABL_GLYPHS_ASCII[$(( RANDOM % ABL_NUM_ASCII ))]}"
                fi
                local f_color="$ABL_C_GREEN_DARK"
                if (( step > 20 && RANDOM % 100 < 5 )); then
                    f_color="$ABL_C_WHITE_PEAK"
                fi
                FRAME_BUFFER+="${ABL_ESC}[${headY};${x}H${f_color}${g_char}"
            fi
            ABL_col_y[$x]=$(( ABL_col_y[$x] + 1 ))
        done
        printf "%b" "${FRAME_BUFFER}${ABL_C_RESET}"
        delay=$(awk -v d="$delay" 'BEGIN {print d + 0.007}')
        abl_safe_sleep "$delay"
    done
}

# ==============================================================================
# PHASE 6: DIGITAL SCANLINE DISSOLVE & ABLITERATED AI REVEAL
# ==============================================================================
phase6_logo_reveal() {
    local logo=(
        "    _____ ___.   .__  .__  __                       __             .___    _____  .___ "
        "  /  _  \\\\_ |__ |  | |__|/  |_  ________________ _/  |_  ____   __| _/   /  _  \\ |   |"
        " /  /_\\  \\| __ \\|  | |  \\   __\\/ __ \\_  __ \\__  \\\\   __\\/ __ \\ / __ |   /  /_\\  \\|   |"
        "/    |    \\ \\_\\ \\  |_|  ||  | \\  ___/|  | \\// __ \\|  | \\  ___// /_/ |  /    |    \\   |"
        "\\____|__  /___  /____/__||__|  \\___  >__|  (____  /__|  \\___  >____ |  \\____|__  /___|"
        "        \\/    \\/                   \\/           \\/          \\/     \\/          \\/     "
    )
    local logo_count=${#logo[@]}
    local subtitle="A B L I T E R A T E D   A I   /   N E U R A L   O R C H E S T R A T O R"

    local logo_y=$(( (ABL_H - logo_count - 6) / 2 ))
    (( logo_y < 2 )) && logo_y=2

    # Measure max logo width
    local max_w=0
    for (( i = 0; i < logo_count; i++ )); do
        local line_len=${#logo[$i]}
        (( line_len > max_w )) && max_w=$line_len
    done

    local box_top=$(( logo_y - 1 ))
    local box_bottom=$(( logo_y + logo_count + 5 ))
    local box_left=$(( (ABL_W - max_w - 6) / 2 ))
    local box_right=$(( box_left + max_w + 6 ))
    (( box_left < 1 )) && box_left=1
    (( box_right > ABL_W )) && box_right=$ABL_W

    # Digital Scanline Dissolve
    for (( y = box_top; y <= box_bottom; y++ )); do
        if (( y >= 1 && y <= ABL_H )); then
            local clear_str=""
            for (( x = box_left; x <= box_right; x++ )); do
                clear_str+=" "
            done
            printf "%b" "${ABL_ESC}[${y};${box_left}H${clear_str}"
            abl_safe_sleep 0.015
        fi
    done

    # Paint ASCII Logo with Luminance Gradient (Dark Green -> Bright Green -> Peak White)
    local logo_colors=(
        "$ABL_C_GREEN_DARK"
        "$ABL_C_GREEN_MID"
        "$ABL_C_GREEN_BRIGHT"
        "$ABL_C_GREEN_NEON"
        "$ABL_C_WHITE_PEAK"
    )

    for (( i = 0; i < logo_count; i++ )); do
        local line="${logo[$i]}"
        local lx=$(( (ABL_W - ${#line}) / 2 ))
        (( lx < 1 )) && lx=1
        local ly=$(( logo_y + i ))
        local color="${logo_colors[$i]:-$ABL_C_GREEN_BRIGHT}"

        printf "%b" "${ABL_ESC}[${ly};${lx}H${color}${line}${ABL_C_RESET}"
        abl_safe_sleep 0.05
    done

    # Reveal Subtitle with Pulse
    local sub_y=$(( logo_y + logo_count + 1 ))
    abl_write_centered "$subtitle" "$sub_y" "$ABL_C_CYAN"
    abl_safe_sleep 0.15
    abl_write_centered "$subtitle" "$sub_y" "$ABL_C_WHITE_PEAK"
    abl_safe_sleep 0.2
    abl_write_centered "$subtitle" "$sub_y" "$ABL_C_GREEN_NEON"
    abl_safe_sleep 0.3

    # Segmented Cyber Progress Bar
    local bar_width=44
    (( bar_width > ABL_W - 10 )) && bar_width=$(( ABL_W - 10 ))
    local bar_x=$(( (ABL_W - bar_width - 2) / 2 ))
    local bar_y=$(( sub_y + 2 ))

    printf "%b" "${ABL_ESC}[${bar_y};${bar_x}H${ABL_C_CYAN}[${ABL_ESC}[${bar_y};$(( bar_x + bar_width + 1 ))H]${ABL_C_RESET}"

    for (( p = 0; p < bar_width; p++ )); do
        local percent=$(( (p + 1) * 100 / bar_width ))
        printf "%b" "${ABL_ESC}[${bar_y};$(( bar_x + 1 + p ))H${ABL_C_WHITE_PEAK}="
        printf "%b" "${ABL_ESC}[$(( bar_y + 1 ));$(( bar_x + (bar_width / 2) - 4 ))H${ABL_C_GREEN_NEON}${percent}% COMPLETE${ABL_C_RESET}"
        abl_safe_sleep 0.030
    done

    # Flash completion pulse
    printf "%b" "${ABL_ESC}[${bar_y};$(( bar_x + 1 ))H${ABL_C_GREEN_NEON}"
    for (( p = 0; p < bar_width; p++ )); do printf "="; done
    printf "%b" "$ABL_C_RESET"
    abl_safe_sleep 0.2
    
    # Pulse logo white
    for (( i = 2; i < logo_count; i++ )); do
        local line="${logo[$i]}"
        local lx=$(( (ABL_W - ${#line}) / 2 ))
        (( lx < 1 )) && lx=1
        local ly=$(( logo_y + i ))
        printf "%b" "${ABL_ESC}[${ly};${lx}H${ABL_C_WHITE_PEAK}${line}${ABL_C_RESET}"
    done
    abl_safe_sleep 0.15
    # Return to neon
    for (( i = 2; i < logo_count; i++ )); do
        local line="${logo[$i]}"
        local lx=$(( (ABL_W - ${#line}) / 2 ))
        (( lx < 1 )) && lx=1
        local ly=$(( logo_y + i ))
        printf "%b" "${ABL_ESC}[${ly};${lx}H${ABL_C_GREEN_NEON}${line}${ABL_C_RESET}"
    done
    abl_safe_sleep 0.8
    
    # Screen wipe for skull
    printf "%b" "${ABL_ESC}[2J"
    abl_safe_sleep 0.1

    # Render Skull ASCII Art
    # Skull ASCII art - array elements are per-line strings; literal \n within
    # strings are intentional content, not newlines (I-24)
    local skull_ascii=(
        "@%%@#@@@@@@%@@@"
        "@#%%%%%%%%@%%%%%%%%%%%%%%%%%%%%%"
        "%%%%%%%%%#%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%##@"
        "@%%@@@%%%#%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%*-%%%%%"
        "@@%%%%@@@@@%#%%%%%@%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%#%%%%%%%%%#"
        "=@%%%%%#%%%%%@%@%%%%%%%%%%%%%%@%%%%%%%%%%%%#%%%%%@%%#@%%@:-+%%%+=="
        "%%%+%%%%%%@%%%%%@@%%%@@%%%%%%%%%#%%%%%%%%%%@%%%@%%@%%-%%%#%%%%%--"
        "%%%%@@@@@@@@%%%%%%@@@@@%%%%@%#%%@%%%%%%%%%%%%%%%%%%%%%%%%%%%:-#%%%#-=::+#"
        "* #%%%%%%+%%%%%%%%%@%%%%%%%%%%%%%#@%%%@#%%%%%%%%%%%%%%%%@@%%%%%%%::+%%#-: ::=#"
        "@ .-%%%%%%@@@%%%%%%%%%%%@%%%%%%%%%%%%% @%@%%%%@%%%%%%%%%%%%%%%%%%+:=::*:"
        "@%%@%  %%%%%%#%%%%%%%@%%%@@%%%%%%%%%%%%@%%%%%%@%%%%%%@%%@%%#%%% %%%%% %###=-:#####"
        "@@%@%-: %%%%*==::%%%%%%%%%%%++##%%%%%%%%%%%%%%%@%%%%%%%%%%%@@%%%%%@%%%%% -::: **#+%#-:"
        "*  % :@%@%#: %%%  %%%%%%#%%%%%%%%% %%%%@%%%%%@%%%@%+%%%@@ #%@%%%%@%+%%#+%*:: %%#-: .=#+"
        "%%%%%%@* : ==  %%%#%%%%%%%%%%%%@%%%%%%%%% #%%%%%#%%%%%%%%%+ %%%%# %%%#%%*.::: :  :.="
        "@@%%%%@%+    .+#%%%%%%@@@%%@%%%@%%%%%%@%%@@%@#%%%%#%%%%%%%%%%%%# :+%%%%% %% :::::.::::"
        "%%%@@%%  .- :%#%@@%%@%%%@%@%@%%@@%%%%#%%%%%%%%%=+%%%%@%%%@%%%@ -: %%%#=-:+-::::::::::"
        "#@%@%@@%%: %%%%#%%%%%@%%%%%%%%%%@@%%%%%%%%%%%%%@@%@%#%%%%%%%%% :***==:. ::::::=-"
        "+%%%+%%@@@%#%%%%%@@@%%%%%%%%%@ %%%%%%%%%%%%%%%%%%@@%%%%%%%%%%%%#%%# :::: #: :::-+-::+-:"
        "%%%%.%%%%%+%%%@%%%%%@%%%%%#%#%%%%@%%@%%@%%%%%%%%%%%%%#%%%%#%%%@%% .:-+::+-::-:: :."
        "%%%%%%%%+%%@%#@%%%%%%%%%%%%@%%%@%%%%%%%%%%%%#%%%%%%%%%#%@%%%#++-:+ :-%# .: ::. ::  :"
        "%%@%%%# %%%%%@%%@%#%%%%%%%==%%%@%%%%%%%%@%%%%@@%%%%%%%%%% %%%%%%%*: -:::::::::::-: ::::::"
        "%%%%%%#- #%%%%%%%#%%%%%%%%@%%%%@%%%%%%@%%%%%%%%#%%%%%%%%%%%%# -*::%# : : : : : :: :  :-:::"
        "%%%%%%#+ # %%%%%%%%%# %%%@%%%%%%#%%%%%%#%%%%%%%#%%%%%%%%%%%# +--%%# * -:::::::::::: ::-"
        "@%%%%%%** %@%%%%%%%%#%%%%%%%%%%%%%%%%#%%%%%%%%%%%%%%%%%%%%% %%%% :=+%% : :::. :  ::::-"
        "%+ ##+%%%  #%%%%%% %%%%@%%%%%%%%%%#%%%%#%%%%%%%%%%%%#%%%@%%#+= :::-: : .  ::::::-"
        "%%+### %&  %%%#%%%%@@%%%%%%@%%%%%%%%#%%%#%%%%@%%%%%% *#%%%%%%##%@%# :-++  .::::::-"
        "%%#%#=- +  .%%%@%%%%%#@%%%%@%%%%%%%@%%%%%%%%%%%%% %%%%%%%%%% @%%:-%## : -= :  .::-:"
        "+****#%%   %%==%@%@%%%%@%%@%#%%%@%%%%%%%%%%%%%%#%%%%%%%%%%%%%%%%%+ *#=::=  .--. .: :--"
        "*#:: %%   #@%-%%%%%@@@%%#%%%%@%@%#%%%%%%%%%%%%#%%%%%%%%%%=%%* -%%%#= -:++-   .:::-"
        "***+- +  #%%%@%#%%%#%%@%%*%%%%%@%%@%%**#%%%@%%%%%%%%%%%%%%:=%%%%% % --%%#*--    .:::"
        "#= *   %%%%%@%%+:  +#%@%#+ :%%%%%%%%%%%%%%%#%%%%%%+**#%: %+      .:##+#=::  ::"
        "%   =+%%%%%                 ++  %%%%%%%%#%=:+%@@%% %%%-::#%           **-  ::"
        "=  %%##*                     +%@%%%%%@#+ *%%%%##%%*:                 =-::  ::"
        "- #%%+                        +%%#+=- =%#  :+%@%+                   :--   .:"
        "%%%%%                          -%%%%%                            +-:-"
        "%%%%                         :=##%%%%%%%%**                       +--"
        "%%%#                          +%%#@@%%@%%                        +#=-"
        "%%%%                         =+++++++++++++                       :-::"
        "%%%%                        +%%%%@ +-: @%%##:                     +%=-."
        "%: :#%%%%%%#                    := %%%%%%      %%%%%% ==                *+# -*::  :="
        "%%%%%%%%%%=+-     -*  *#%%%%%%%#%%#             %%%%%%%##%: *+           .-::::::::#:::"
        "%-%%%%%%# +%%%%%%%%%%#%%%%%%%%%%%%#            :%%%%%%#%*#%%*:-##=-:=--+-- .**::-"
        "@%%%%%%%@%%%%%%%%%%#%%%%%%%%%%%%%%%             +%%%%%%%%%+ *%%#  :-=+-+:::: :##::::"
        "@@ %%%%%%%%%%%%%%.    :%%%%%%%                  =%%%%%%#+-  :-#+:::-=-::::=--:"
        "#%%%%%%%%# #+#%*     +%%%%%+%+                 #%%%%%%%     .::::::::::=--:::"
        "%%%%%%%%%#-------==#%  %%%%@:       =          =#%%%%%+ .-*:::: :#:::::.-"
        "-@#%#%::-     --+##%%%#%%%%%#      #*         %%%%%% :#*+::.      .-=-=::"
        "+%%=------- *%# --             *%%%%%##%# :-."
        ": %%%%%% #%%%%###@%#%%%%%%#%*:*%#=-."
        "#: %%%%#%@%%%%%%%%#%*%%%%%%%% %%%*+: :"
        "**+%%%%%%%%%%%%%%%%%%%%%#%%%#%# =*=-: -"
        "++%%%%%%%%%%%%%%%%%%%%%*%%%##%%#=**:. ."
        "%:#: %-++%%%%%%%%#%%%%%+*--=-  :- -:"
        "#*% %%%  .%%%: =%%% := #%@  %=- -= +% :-."
        "*%-%#% =%%% @%%% =%%% =%%# ##* :*:"
        "#%# =%%%% %%%% =%%%+ ====  %: :"
        ": %%%- *%%%% =%%% = %%%."
        "=--   :=+"
    )
    
    local s_count=${#skull_ascii[@]}
    local sy=$(( (ABL_H - s_count) / 2 ))
    (( sy < 1 )) && sy=1

    # Print skull line by line
    for (( i = 0; i < s_count; i++ )); do
        local line="${skull_ascii[$i]}"
        local sx=$(( (ABL_W - ${#line}) / 2 ))
        (( sx < 1 )) && sx=1
        
        local c_line="${line//@/${ABL_C_WHITE_PEAK}@${ABL_C_GREEN_DARK}}"
        c_line="${c_line//%/${ABL_C_GREEN_BRIGHT}%${ABL_C_GREEN_DARK}}"
        c_line="${c_line//#/${ABL_C_GREEN_MID}#${ABL_C_GREEN_DARK}}"
        c_line="${c_line//*/${ABL_C_RED}*${ABL_C_GREEN_DARK}}"
        c_line="${c_line//=/${ABL_C_GREEN_NEON}=${ABL_C_GREEN_DARK}}"

        printf "%b" "${ABL_ESC}[$((sy + i));${sx}H${ABL_C_GREEN_DARK}${c_line}${ABL_C_RESET}"
        abl_safe_sleep 0.02
    done
    
    # Pulse skull briefly
    abl_safe_sleep 1.5
    
    # Dissolve skull
    for (( y = sy; y < sy + s_count; y+=2 )); do
        printf "%b" "${ABL_ESC}[${y};1H${ABL_ESC}[2K"
        abl_safe_sleep 0.04
    done
}

# ==============================================================================
# MAIN ORCHESTRATION PIPELINE
# ==============================================================================
abl_show_help() {
    printf "%b\n" "${ABL_C_WHITE_PEAK}ABLITERATED AI - MATRIX TERMINAL ENGINE (macOS & POSIX)${ABL_C_RESET}"
    printf "%b\n" "Usage: $0 [OPTIONS]"
    printf "%b\n" ""
    printf "%b\n" "Options:"
    printf "%b\n" "  --one-shot      Run cinematic boot sequence & logo reveal, then exit cleanly."
    printf "%b\n" "  --screensaver   Skip cinematic intro and launch directly into matrix screensaver."
    printf "%b\n" "  --ascii         Force cyber ASCII character set (instead of Katakana)."
    printf "%b\n" "  --katakana      Force Japanese half-width Katakana glyph set (default)."
    printf "%b\n" "  --test          Run automated self-test across all phases (rapid validation)."
    printf "%b\n" "  -h, --help      Display this help menu."
    printf "%b\n" ""
    printf "%b\n" "Screensaver Controls:"
    printf "%b\n" "  [SPACE]         Pause / Resume rain"
    printf "%b\n" "  [+] / [-]       Increase / Decrease speed"
    printf "%b\n" "  [K]             Toggle between Katakana and ASCII glyphs"
    printf "%b\n" "  [Q] or [ESC]    Clean disconnect / exit"
    (( _ABL_IS_SOURCED )) && return 0 || exit 0
}

main() {
    local mode="hybrid"
    # Parse command-line arguments
    abl_parse_args() {
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --speed)
                    ABL_SPEED_MULTIPLIER="$2"
                    shift 2
                    ;;
                --grid-output)
                    ABL_GENERATE_GRID=1
                    shift
                    ;;
                --mode)
                    mode="$2"
                    shift 2
                    ;;
                --one-shot|--oneshot)
                    mode="oneshot"
                    shift
                    ;;
                --screensaver)
                    mode="screensaver"
                    shift
                    ;;
                --ascii)
                    ABL_USE_KATAKANA=0
                    shift
                    ;;
                --katakana)
                    ABL_USE_KATAKANA=1
                    shift
                    ;;
                --test)
                    mode="test"
                    shift
                    ;;
                -h|--help)
                    abl_show_help
                    ;;
                *)
                    shift
                    ;;
            esac
        done
    }
    abl_parse_args "$@"
    abl_init_sleep_cache

    local rain_time=8000
    local is_test=0

    

    if [[ "$mode" == "screensaver" ]]; then
        local footer="[ SPACE: Pause ]   [ +/-: Speed ]   [ K: Toggle Glyphs ]   [ Q: Disconnect ]"
    abl_write_centered "$footer" $(( ABL_H - 1 )) "$ABL_C_CYAN"
        abl_run_matrix_rain 0 0.03 1
        return
    fi

    if [[ "$mode" == "test" ]]; then
        # Rapid automated validation
        phase1_hex_dump
        phase3_cipher_decrypt
        abl_run_matrix_rain 1500 0.02 0
        phase5_slowdown_freeze
        phase6_logo_reveal
        abl_cleanup
        return
    fi

    # Phase 1: Cryptographic Hex Uplink
    phase1_hex_dump
    abl_advance_timeline "Phase 1"

    # Phase 2: Hydra v2 Root Escalation & Eli Consciousness
    phase2_hydra_escalation
    abl_advance_timeline "Phase 2"

    # Phase 3: Hollywood Cipher Decryption
    phase3_cipher_decrypt
    abl_advance_timeline "Phase 3"

    # Phase 4: Full Matrix Cascade (Cinematic 8-second rain split into two acts)
    abl_run_matrix_rain 3000 0.035 0
    abl_run_matrix_rain 5000 0.020 0 1
    abl_advance_timeline "Phase 4"

    # Phase 5: Time Dilation & Gravitational Freeze
    phase5_slowdown_freeze
    abl_advance_timeline "Phase 5"

    # Phase 6: Abliterated AI Logo Reveal
    phase6_logo_reveal
    abl_advance_timeline "Phase 6"

    if [[ "$mode" == "oneshot" ]]; then
        abl_safe_sleep 1.0
        abl_cleanup
    fi

    # Phase 7: Interactive Cyber Matrix Screensaver
    local footer="[ SPACE: Pause ]   [ +/-: Speed ]   [ K: Toggle Glyphs ]   [ Q: Disconnect ]"
    abl_write_centered "$footer" $(( ABL_H - 1 )) "$ABL_C_CYAN"
    abl_run_matrix_rain 0 0.03 1
    abl_post_execution_artifacts
}

# Execute
if (( _ABL_IS_SOURCED == 0 )); then
    main "$@"
fi

