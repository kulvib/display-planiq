import { Box, Typography } from "@mui/material";

export default function PlanIQFooter() {
  return (
    <Box
      component="footer"
      sx={{
        flexShrink: 0,
        width: "100%",
        minWidth: 0,
        minHeight: 40,
        py: 1.25,
        px: 2,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <Typography
        variant="caption"
        sx={{ textAlign: "center", color: "#cbd5e1", fontSize: 12, lineHeight: 1.5 }}
      >
        © {new Date().getFullYear()} PlanIQ. Alle rettigheder forbeholdes.
      </Typography>
    </Box>
  );
}
