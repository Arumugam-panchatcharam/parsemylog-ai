import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Divider, Chip } from "@mui/material";
import { APP_VERSION, APP_NAME, APP_DESCRIPTION, PROJECT_INFO, TECH_STACK, FEATURES } from "@/config/version";
import InfoIcon from "@mui/icons-material/Info";
import CodeIcon from "@mui/icons-material/Code";
import StorageIcon from "@mui/icons-material/Storage";
import PsychologyIcon from "@mui/icons-material/Psychology";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import GitHubIcon from "@mui/icons-material/GitHub";
import logoImg from "@/assets/logo.png";

interface AboutDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function AboutDialog({ open, onClose }: AboutDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle className="flex items-center gap-3 pb-2">
        <img src={logoImg} alt={APP_NAME} className="h-10 w-10" />
        <div>
          <div className="text-xl font-bold">{APP_NAME}</div>
          <div className="text-sm text-muted-foreground font-normal">Version {APP_VERSION}</div>
        </div>
      </DialogTitle>

      <DialogContent dividers>
        {/* Description */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            <InfoIcon className="text-primary" fontSize="small" />
            <h3 className="font-semibold text-base">About</h3>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {APP_DESCRIPTION}
          </p>
        </div>

        <Divider className="my-4" />

        {/* Key Features */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircleIcon className="text-primary" fontSize="small" />
            <h3 className="font-semibold text-base">Key Features</h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {FEATURES.map((feature, idx) => (
              <Chip
                key={idx}
                label={feature}
                size="small"
                variant="outlined"
                className="text-xs"
              />
            ))}
          </div>
        </div>

        <Divider className="my-4" />

        {/* Tech Stack */}
        <div className="mb-6">
          <h3 className="font-semibold text-base mb-3">Tech Stack</h3>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Frontend */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <CodeIcon className="text-blue-500" fontSize="small" />
                <h4 className="font-medium text-sm">Frontend</h4>
              </div>
              <ul className="text-xs text-muted-foreground space-y-1 ml-6">
                {TECH_STACK.frontend.map((tech, idx) => (
                  <li key={idx} className="list-disc">{tech}</li>
                ))}
              </ul>
            </div>

            {/* Backend */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <StorageIcon className="text-green-500" fontSize="small" />
                <h4 className="font-medium text-sm">Backend</h4>
              </div>
              <ul className="text-xs text-muted-foreground space-y-1 ml-6">
                {TECH_STACK.backend.map((tech, idx) => (
                  <li key={idx} className="list-disc">{tech}</li>
                ))}
              </ul>
            </div>

            {/* Machine Learning */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <PsychologyIcon className="text-purple-500" fontSize="small" />
                <h4 className="font-medium text-sm">Machine Learning</h4>
              </div>
              <ul className="text-xs text-muted-foreground space-y-1 ml-6">
                {TECH_STACK.machineLearning.map((tech, idx) => (
                  <li key={idx} className="list-disc">{tech}</li>
                ))}
              </ul>
            </div>

            {/* Data Stores */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <StorageIcon className="text-orange-500" fontSize="small" />
                <h4 className="font-medium text-sm">Data Stores</h4>
              </div>
              <ul className="text-xs text-muted-foreground space-y-1 ml-6">
                {TECH_STACK.dataStores.map((tech, idx) => (
                  <li key={idx} className="list-disc">{tech}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <Divider className="my-4" />

        {/* Project Information */}
        <div className="text-xs text-muted-foreground space-y-1">
          <div className="flex justify-between">
            <span className="font-medium">License:</span>
            <span>{PROJECT_INFO.license}</span>
          </div>
          <div className="flex justify-between">
            <span className="font-medium">Build Date:</span>
            <span>{PROJECT_INFO.buildDate}</span>
          </div>
          {PROJECT_INFO.repository && (
            <div className="flex justify-between items-center">
              <span className="font-medium">Repository:</span>
              <a
                href={PROJECT_INFO.repository}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline flex items-center gap-1"
              >
                <GitHubIcon fontSize="small" />
                GitHub
              </a>
            </div>
          )}
        </div>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} variant="contained">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}
