// Mensarium.app launcher: runs the agent as a child process so macOS attributes permission prompts
// (Screen Recording, Accessibility) to Mensarium instead of the Python interpreter.
// Build: make launcher (universal, ad-hoc signed). Usage: Mensarium <program> [args...]
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s program [args...]\n", argv[0]);
        return 64;
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    for (;;) {
        int status = 0;
        if (posix_spawnp(&child, argv[1], NULL, NULL, argv + 1, environ) != 0) {
            perror("mensarium launcher: spawn failed");
            return 71;
        }
        while (waitpid(child, &status, 0) < 0) {
        }
        child = 0;
        if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
        int code = WEXITSTATUS(status);
        // the agent re-execs itself after an update; launchd restarts us on any exit, so just report it
        return code;
    }
}
